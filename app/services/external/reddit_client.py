"""
Reddit API — async service wrapper (PRAW).

PRAW is a synchronous library, so all blocking calls are dispatched
to a background thread via ``asyncio.to_thread``.

Public interface
────────────────
    client = RedditClient()

    threads = await client.fetch_hot_threads("python", limit=15)
    post    = await client.fetch_post_details("1abc2de")
    comments = await client.fetch_top_comments("1abc2de", limit=30)

All methods return **Pydantic v2 models** for type-safe downstream use.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import praw
from praw.exceptions import (
    PRAWException,
    RedditAPIException,
)
from prawcore.exceptions import (
    Forbidden,
    NotFound,
    ResponseException,
    ServerError,
    TooManyRequests,
)
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic Response Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RedditComment(BaseModel):
    """A single Reddit comment."""
    comment_id: str
    author: str = "[deleted]"
    body: str = ""
    score: int = 0
    created_utc: float = 0.0
    permalink: str = ""
    is_submitter: bool = False
    edited: bool = False
    depth: int = 0


class RedditThread(BaseModel):
    """A Reddit post / submission (without full comment tree)."""
    post_id: str
    subreddit: str
    title: str
    author: str = "[deleted]"
    selftext: str = ""
    url: str = ""
    permalink: str = ""
    score: int = 0
    upvote_ratio: float = 0.0
    num_comments: int = 0
    created_utc: float = 0.0
    is_self: bool = True
    link_flair_text: Optional[str] = None
    over_18: bool = False
    thumbnail: Optional[str] = None


class HotThreadsResponse(BaseModel):
    """Batch of hot threads from a subreddit."""
    subreddit: str
    count: int = 0
    threads: list[RedditThread] = Field(default_factory=list)


class PostDetailResponse(BaseModel):
    """A full post with its top comments."""
    post: RedditThread
    comments: list[RedditComment] = Field(default_factory=list)


class TopCommentsResponse(BaseModel):
    """Top-level comments for a post."""
    post_id: str
    count: int = 0
    comments: list[RedditComment] = Field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Custom Exceptions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RedditClientError(Exception):
    """Base exception for Reddit client errors."""


class RedditRateLimited(RedditClientError):
    """Raised when Reddit rate-limits our requests."""


class RedditResourceNotFound(RedditClientError):
    """Raised when the requested subreddit or post does not exist."""


class RedditForbidden(RedditClientError):
    """Raised when access to the resource is denied (private sub, etc.)."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Client
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2  # seconds


class RedditClient:
    """Async wrapper around PRAW (Python Reddit API Wrapper).

    Parameters
    ----------
    client_id : str | None
        Reddit OAuth2 client ID.  Falls back to ``Settings``.
    client_secret : str | None
        Reddit OAuth2 secret.  Falls back to ``Settings``.
    user_agent : str | None
        User-agent string.  Falls back to ``Settings``.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        settings = get_settings()
        self._client_id = client_id or settings.REDDIT_CLIENT_ID
        self._client_secret = client_secret or settings.REDDIT_CLIENT_SECRET
        self._user_agent = user_agent or settings.REDDIT_USER_AGENT

        if not self._client_id or not self._client_secret:
            raise ValueError(
                "Reddit client ID and secret are required. Set "
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in your .env "
                "file or pass them directly to RedditClient()."
            )

        self._reddit = praw.Reddit(
            client_id=self._client_id,
            client_secret=self._client_secret,
            user_agent=self._user_agent,
        )

    # ── internal helpers ─────────────────────────────────────

    async def _run_in_thread(self, func, *args, **kwargs):
        """Execute a synchronous PRAW call in a background thread
        with retry logic for transient failures.
        """
        last_error: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)

            except TooManyRequests as exc:
                wait = _RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "Reddit rate-limited (attempt %d/%d) — retrying in %ds",
                    attempt, _MAX_RETRIES, wait,
                )
                last_error = exc
                await asyncio.sleep(wait)

            except NotFound as exc:
                raise RedditResourceNotFound(
                    f"Reddit resource not found: {exc}"
                ) from exc

            except Forbidden as exc:
                raise RedditForbidden(
                    f"Access denied to Reddit resource: {exc}"
                ) from exc

            except ServerError as exc:
                wait = _RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "Reddit server error (attempt %d/%d) — retrying in %ds",
                    attempt, _MAX_RETRIES, wait,
                )
                last_error = exc
                await asyncio.sleep(wait)

            except ResponseException as exc:
                raise RedditClientError(
                    f"Reddit API response error: {exc}"
                ) from exc

            except RedditAPIException as exc:
                raise RedditClientError(
                    f"Reddit API error: {exc}"
                ) from exc

            except PRAWException as exc:
                raise RedditClientError(
                    f"PRAW error: {exc}"
                ) from exc

        # All retries exhausted
        raise RedditRateLimited(
            f"Reddit API call failed after {_MAX_RETRIES} retries: {last_error}"
        )

    @staticmethod
    def _submission_to_schema(submission) -> RedditThread:
        """Convert a PRAW Submission to our Pydantic schema."""
        return RedditThread(
            post_id=submission.id,
            subreddit=str(submission.subreddit),
            title=submission.title,
            author=str(submission.author) if submission.author else "[deleted]",
            selftext=submission.selftext or "",
            url=submission.url,
            permalink=f"https://reddit.com{submission.permalink}",
            score=submission.score,
            upvote_ratio=submission.upvote_ratio,
            num_comments=submission.num_comments,
            created_utc=submission.created_utc,
            is_self=submission.is_self,
            link_flair_text=submission.link_flair_text,
            over_18=submission.over_18,
            thumbnail=submission.thumbnail if submission.thumbnail != "self" else None,
        )

    @staticmethod
    def _comment_to_schema(comment, depth: int = 0) -> RedditComment:
        """Convert a PRAW Comment to our Pydantic schema."""
        return RedditComment(
            comment_id=comment.id,
            author=str(comment.author) if comment.author else "[deleted]",
            body=comment.body or "",
            score=comment.score,
            created_utc=comment.created_utc,
            permalink=f"https://reddit.com{comment.permalink}",
            is_submitter=comment.is_submitter,
            edited=bool(comment.edited),
            depth=depth,
        )

    # ── public API ───────────────────────────────────────────

    async def fetch_hot_threads(
        self,
        subreddit_name: str,
        *,
        limit: int = 25,
    ) -> HotThreadsResponse:
        """Fetch hot threads from a subreddit.

        Parameters
        ----------
        subreddit_name : str
            Name of the subreddit (without ``r/`` prefix).
        limit : int
            Number of threads to fetch (default 25, max 100).

        Returns
        -------
        HotThreadsResponse
            List of hot threads with metadata and engagement stats.
        """

        def _fetch():
            subreddit = self._reddit.subreddit(subreddit_name)
            return list(subreddit.hot(limit=min(limit, 100)))

        submissions = await self._run_in_thread(_fetch)

        threads = [
            self._submission_to_schema(sub) for sub in submissions
        ]

        return HotThreadsResponse(
            subreddit=subreddit_name,
            count=len(threads),
            threads=threads,
        )

    async def fetch_post_details(
        self,
        post_id: str,
        *,
        comment_limit: int = 20,
        comment_sort: str = "best",
    ) -> PostDetailResponse:
        """Fetch a single post with its top comments.

        Parameters
        ----------
        post_id : str
            Reddit post / submission ID (e.g. ``"1abc2de"``).
        comment_limit : int
            Maximum number of top-level comments to include (default 20).
        comment_sort : str
            Comment sort order — ``"best"`` (default), ``"top"``,
            ``"new"``, ``"controversial"``, ``"old"``, ``"q&a"``.

        Returns
        -------
        PostDetailResponse
            The post with its top-level comments.
        """

        def _fetch():
            submission = self._reddit.submission(id=post_id)
            submission.comment_sort = comment_sort
            submission.comments.replace_more(limit=0)  # skip "load more"
            return submission

        submission = await self._run_in_thread(_fetch)

        post = self._submission_to_schema(submission)

        comments: list[RedditComment] = []
        for comment in submission.comments[:comment_limit]:
            comments.append(self._comment_to_schema(comment, depth=0))

        return PostDetailResponse(post=post, comments=comments)

    async def fetch_top_comments(
        self,
        post_id: str,
        *,
        limit: int = 30,
        sort: str = "top",
        include_replies: bool = False,
        reply_depth: int = 1,
    ) -> TopCommentsResponse:
        """Fetch top-level comments for a post (optionally with replies).

        Parameters
        ----------
        post_id : str
            Reddit post ID.
        limit : int
            Maximum number of top-level comments (default 30).
        sort : str
            Sort order — ``"top"`` (default), ``"best"``, ``"new"``,
            ``"controversial"``.
        include_replies : bool
            If ``True``, also fetch first-level replies for each
            comment (default ``False``).
        reply_depth : int
            How many levels of nested replies to include when
            ``include_replies`` is ``True`` (default 1).

        Returns
        -------
        TopCommentsResponse
            Flat or nested list of comments.
        """

        def _fetch():
            submission = self._reddit.submission(id=post_id)
            submission.comment_sort = sort
            submission.comments.replace_more(limit=0)
            return submission

        submission = await self._run_in_thread(_fetch)

        comments: list[RedditComment] = []
        for comment in submission.comments[:limit]:
            comments.append(self._comment_to_schema(comment, depth=0))

            if include_replies:
                for reply in comment.replies[:limit]:
                    if hasattr(reply, "body"):
                        comments.append(
                            self._comment_to_schema(reply, depth=1)
                        )
                        # Optionally go deeper
                        if reply_depth > 1:
                            for nested in reply.replies[:limit]:
                                if hasattr(nested, "body"):
                                    comments.append(
                                        self._comment_to_schema(nested, depth=2)
                                    )

        return TopCommentsResponse(
            post_id=post_id,
            count=len(comments),
            comments=comments,
        )
