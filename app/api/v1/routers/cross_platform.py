"""
Cross-Platform Router  —  /api/v1/cross-platform
===================================================

The core analytical endpoint that bridges YouTube and Reddit data according to the PRD:
"Cross-Platform Mode links YouTube videos with Reddit posts and discussions that reference
the same content. It combines platform-specific engagement metrics, timestamps, sentiment,
topics, and discussion activity to show how content propagates across platforms and how
audience response differs between YouTube and Reddit."

Endpoints
---------
GET /shared-videos
    Scans Reddit comments for YouTube video URLs, looks up YouTube metadata,
    and returns linked videos enriched with timestamps, propagation delay,
    audience sentiment comparison, topics, and detailed Reddit discussion threads.

GET /sentiment-comparison
    Compares audience sentiment distribution (positive/neutral/negative) between
    YouTube and Reddit for a scanned subreddit or across all tracked accounts.

GET /topic-correlation
    Extracts and correlates discussion topics and keywords between YouTube videos
    and Reddit discussion threads.

GET /top-videos
    Live topic search on YouTube Data API sorted by view count.

GET /engagement-comparison
    Computes a normalised engagement index (0–100) for each tracked account.

GET /correlation-summary
    Unified payload combining shared videos, engagement, sentiment, and topics.
"""

from __future__ import annotations

import asyncio
import re
import string
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_asyncio = asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    CrossPlatformCorrelationResponse,
    CrossPlatformSentimentComparison,
    CrossPlatformTopicCorrelation,
    PlatformEngagementComparison,
    PlatformSentimentBreakdown,
    RedditDiscussionItem,
    SharedVideoItem,
    VideoCrossPlatformEngagementResponse,
)
from app.db.mongodb import get_comments_collection, get_video_payloads_collection
from app.db.postgres import Platform, PlatformAccount, get_db_session
from app.services.analytics.sentiment_service import SentimentService

router = APIRouter(prefix="/cross-platform", tags=["Cross-Platform"])

# ── YouTube URL regex — captures youtu.be, youtube.com/watch, embed, shorts, etc. ──
_YT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtu\.be/|youtube\.com/(?:watch\?.*?v=|embed/|v/|shorts/))"
    r"([A-Za-z0-9_\-]{11})"
)


def _extract_video_id(input_str: Any) -> Optional[str]:
    """Extract canonical 11-char YouTube video ID from URL or raw ID."""
    if not input_str or not isinstance(input_str, str):
        return None
    input_str = input_str.strip()
    match = _YT_URL_RE.search(input_str)
    if match:
        return match.group(1)
    # Check if raw 11-character video ID
    clean = re.sub(r"[^A-Za-z0-9_\-]", "", input_str)
    if len(clean) == 11:
        return clean
    return None


# Common stopwords for topic / keyword extraction
_STOPWORDS = frozenset(
    "the a an and or but in on at to for of with by from is are was were be been "
    "being have has had do does did will would could should may might shall can "
    "not no nor so yet both either neither one two three i me my we our you your "
    "he she it its they them their this that these those what which who whom how "
    "when where why than then also just more very much many some any all each "
    "about after before between into through during again further once "
    "http https www ftp youtube watch reddit youtu imgur twitter facebook "
    "amp utm ref source medium campaign com net org video comments"
    .split()
)

_sentiment_svc: SentimentService | None = None


def _get_sentiment_svc() -> SentimentService:
    global _sentiment_svc
    if _sentiment_svc is None:
        _sentiment_svc = SentimentService()
    return _sentiment_svc


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Safely parse an ISO-8601 datetime string to UTC."""
    if not dt_str:
        return None
    try:
        # Standard ISO format (handles Z and offsets)
        cleaned = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _extract_topics_from_texts(texts: List[str], top_n: int = 8) -> List[str]:
    """Extract top topic keywords from a collection of text strings."""
    tokens: List[str] = []
    for text in texts:
        if not text:
            continue
        cleaned = re.sub(r"https?://\S+|www\.\S+", "", text)
        cleaned = cleaned.translate(str.maketrans("", "", string.punctuation + string.digits))
        for word in cleaned.lower().split():
            if len(word) > 3 and word not in _STOPWORDS:
                tokens.append(word)
    return [w for w, _ in Counter(tokens).most_common(top_n)]


def _compute_sentiment_breakdown(labels: List[str]) -> PlatformSentimentBreakdown:
    """Compute normalized sentiment distribution from a list of sentiment labels."""
    if not labels:
        return PlatformSentimentBreakdown(
            positive=0.0, neutral=0.0, negative=0.0, dominant_label="neutral", sample_size=0
        )
    counts = Counter(labels)
    total = len(labels)
    pos_pct = round(counts.get("positive", 0) / total, 3)
    neu_pct = round(counts.get("neutral", 0) / total, 3)
    neg_pct = round(counts.get("negative", 0) / total, 3)

    dominant = "neutral"
    if pos_pct >= neu_pct and pos_pct >= neg_pct:
        dominant = "positive"
    elif neg_pct >= pos_pct and neg_pct >= neu_pct:
        dominant = "negative"

    return PlatformSentimentBreakdown(
        positive=pos_pct,
        neutral=neu_pct,
        negative=neg_pct,
        dominant_label=dominant,
        sample_size=total,
    )


def _empty_breakdown() -> PlatformSentimentBreakdown:
    """Honest zero-sample breakdown — used when no measured comments exist.

    Callers must never fabricate sentiment from like ratios or hardcoded
    distributions; an empty breakdown renders as an explicit "insufficient
    data" state in the dashboard instead of misleading numbers.
    """
    return PlatformSentimentBreakdown(
        positive=0.0, neutral=0.0, negative=0.0, dominant_label="neutral", sample_size=0
    )


def _has_samples(b: PlatformSentimentBreakdown | None) -> bool:
    """Return True when a breakdown is backed by at least one measured comment."""
    return b is not None and b.sample_size > 0


def _sentiment_gap(
    yt: PlatformSentimentBreakdown | None,
    rd: PlatformSentimentBreakdown | None,
    *,
    ndigits: int = 2,
) -> float:
    """Shared positive-sentiment gap (YT positive − Reddit positive).

    Returns 0.0 unless BOTH sides have measured samples — a gap against an
    empty side is meaningless and must not be presented as a finding.
    Single rounding rule for every cross-platform endpoint.
    """
    if not _has_samples(yt) or not _has_samples(rd):
        return 0.0
    return round(yt.positive - rd.positive, ndigits)


def _normalise_engagement(raw: Dict[str, Any], platform: str) -> float:
    """Produce a 0–100 engagement index from raw platform metrics."""
    import math

    if platform == "youtube":
        views = max(1, int(raw.get("views") or 0))
        likes = max(0, int(raw.get("likes") or 0))
        comments = max(0, int(raw.get("comments") or raw.get("comment_count") or 0))
        like_ratio = min(likes / views, 1.0)
        comment_ratio = min(comments / views, 1.0)
        log_views = math.log10(views)
        score = (log_views / 7) * (like_ratio * 50 + comment_ratio * 50)

    elif platform == "reddit":
        upvotes = max(1, int(raw.get("upvotes") or raw.get("members") or raw.get("subscribers") or 0))
        comments = max(0, int(raw.get("comments") or 0))
        # members-only snapshots have no comment count — score on audience size alone
        # instead of multiplying by a zero comment_ratio.
        log_ups = math.log10(upvotes)
        if comments > 0:
            total = max(1, upvotes + comments)
            comment_ratio = min(comments / total, 1.0)
            # Blend reach (50%) with discussion intensity (50%)
            score = (log_ups / 6) * (50 + comment_ratio * 50)
        else:
            score = (log_ups / 6) * 50

    else:
        score = 0.0

    return round(min(max(score, 0.0), 100.0), 2)


async def _fetch_youtube_video_comments(vid_id: str, max_comments: int = 200) -> List[str]:
    """Fetch top comments for a specific YouTube video live via YouTube Data API.

    Supports pagination to fetch up to max_comments comments in batches of 100.
    Sorted by relevance so the most prominent community comments are classified first.
    """
    try:
        from app.services.external.youtube_client import YouTubeClient
        yt_client = YouTubeClient()
        comments: List[str] = []
        page_token = None

        while len(comments) < max_comments:
            remaining = max_comments - len(comments)
            batch_size = min(remaining, 100)  # YouTube API max per page is 100
            params: dict = dict(
                part="snippet",
                videoId=vid_id,
                maxResults=batch_size,
                order="relevance",
                textFormat="plainText",
            )
            if page_token:
                params["pageToken"] = page_token

            req = yt_client._service.commentThreads().list(**params)
            ct_data = await _asyncio.to_thread(req.execute)

            for item in ct_data.get("items", []):
                text = (
                    item.get("snippet", {})
                    .get("topLevelComment", {})
                    .get("snippet", {})
                    .get("textDisplay", "")
                )
                if text and len(text.strip()) > 5:
                    comments.append(text.strip())

            page_token = ct_data.get("nextPageToken")
            if not page_token:
                break  # No more pages available

        return comments
    except Exception:
        return []



# ── Video fingerprint helpers ─────────────────────────────────────────────────

# Stopwords used for title keyword extraction (shared between helpers and endpoint)
_TITLE_STOPWORDS: frozenset = frozenset({
    'how', 'much', 'do', 'you', 'really', 'need', 'in', 'to', 'the', 'a', 'an', 'is', 'are',
    'for', 'of', 'and', 'or', 'on', 'at', 'this', 'that', 'with', 'from', 'what', 'your',
    'video', 'about', 'why', 'can', 'will', 'just', 'best', 'top', 'new', 'vs', 'get', 'has',
    'its', 'my', 'our', 'their', 'all', 'by', 'be', 'was', 'were', 'it', 'he', 'she', 'they',
    'watch', 'youtube', 'reddit', 'i', 'me', 'we', 'are', 'so', 'but', 'if', 'up', 'out',
})
# Known spam/bot subreddits to skip
_SPAM_SUB_RE = re.compile(r'(autonewspaper|bot|moderator|spam|promos|autotldr)', re.I)


def _build_video_fingerprint(
    vid_id: str,
    title: str = "",
    channel_title: str = "",
    tags: Optional[List[str]] = None,
    yt_published_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a structured fingerprint dict for a YouTube video to use in
    multi-signal Reddit discussion verification.

    Returns a dict with:
      - vid_id             : canonical 11-char ID
      - url_patterns       : list of URL/ID strings that unambiguously identify the video
      - creator_variants   : normalized creator name tokens for text matching
      - topic_words        : distinctive content words extracted from the title (≥ 3 chars,
                             stopword-filtered, de-duplicated, sorted by length descending)
      - distinctive_phrases: terms highlighted in the title via *, ", [], () — e.g. *ANARC 2*
                             → "ANARC 2".  Used for high-precision creator+phrase queries.
      - tag_phrases        : cleaned tag strings (lowercased, ≤ 5 tags)
      - title_raw          : original title string (for quoted search)
      - full_text          : title + channel_title + tags joined — for Sentence-BERT encoding
      - published_ts       : UTC Unix timestamp of video publish date (or None)
    """
    tags = tags or []

    # URL patterns that uniquely identify this video
    url_patterns = [
        vid_id,
        f"youtu.be/{vid_id}",
        f"watch?v={vid_id}",
        f"youtube.com/watch?v={vid_id}",
        f"youtube.com/shorts/{vid_id}",
        f"youtube.com/embed/{vid_id}",
    ]

    # Normalize creator name: strip generic suffixes, split into tokens
    clean_creator = re.sub(
        r'\b(official|channel|tv|hd|yt|hindi|english|media|network|productions|studio|studios)\b',
        '',
        channel_title,
        flags=re.I,
    ).strip().lower()
    # Remove any leftover punctuation/digits from creator string
    clean_creator = re.sub(r'[^a-z\s]', '', clean_creator).strip()
    creator_variants: List[str] = []
    if clean_creator:
        creator_variants.append(clean_creator)
        # Also add individual tokens that are >= 3 chars (e.g. "mark" from "mark rober")
        for tok in clean_creator.split():
            if len(tok) >= 3 and tok not in creator_variants:
                creator_variants.append(tok)

    # Enhance creator variants using tags (captures aliases like 'MKBHD')
    # Look for single-word tags >= 5 chars to avoid generic short tags like 'tech'
    for tag in tags:
        clean_tag = tag.lower().strip()
        if ' ' not in clean_tag and len(clean_tag) >= 5 and clean_tag.isalnum():
            # Exclude common generic single-word tags
            if clean_tag not in {"review", "unboxing", "vlog", "podcast", "shorts", "video"}:
                if clean_tag not in creator_variants:
                    creator_variants.append(clean_tag)

    # Extract distinctive topic words from video title
    raw_words = re.findall(r'[a-zA-Z]{3,}', title.lower())
    topic_words = [
        w for w in dict.fromkeys(raw_words)  # preserve order, de-duplicate
        if w not in _TITLE_STOPWORDS
    ]
    # Sort longer words first — they are more distinctive
    topic_words.sort(key=len, reverse=True)

    # ── Extract highlighted / bracketed phrases from the title ────────────────
    # Many YouTubers emphasise the key product/event name using *, ", [], or ().
    # e.g. "Our New Smartwatch is Here ! *ANARC 2*" → ["ANARC 2"]
    # These are high-signal terms perfect for a creator+phrase Reddit query.
    # Generic phrases frequently placed in titles/brackets that should not be queried as distinctive phrases
    _GENERIC_SEGMENTS = {
        'official', 'music', 'video', 'audio', 'lyrics', 'ft', 'feat',
        'full', 'hd', 'full hd', '4k', 'new', 'latest', 'vlog', 'shorts',
        'official video', 'official music video', 'official audio', 'lyric video',
        'official teaser trailer', 'official trailer', 'teaser trailer', 'trailer',
    }

    raw_brackets = re.findall(
        r'[\*\"\[\(]([^\*\"\[\]\(\)]{2,40})[\*\"\]\)]',
        title,
    )
    distinctive_phrases: List[str] = []
    for bp in raw_brackets:
        bp_clean = bp.strip()
        if len(bp_clean) >= 2 and bp_clean.lower() not in _GENERIC_SEGMENTS:
            distinctive_phrases.append(bp_clean)

    # Also extract pipe-separated, dash-separated, colon-separated segments from the title.
    # We use '\s+-\s+' for ASCII hyphens to avoid breaking compound words (e.g. Anti-Hero, Spider-Man).
    # e.g. "My First Press Conference | Open Challenge to Modi | Dhruv Rathee"
    #   → ["My First Press Conference", "Open Challenge to Modi"]
    # These segments are used in Tier-2 Creator+Phrase queries to find threads
    # where users discuss the video by subject without linking the URL.
    _SEGMENT_SPLITTER = re.compile(r'\s*[|–—:]\s*|\s+-\s+')
    for seg in _SEGMENT_SPLITTER.split(title):
        # Strip trailing/leading bracket artifacts if any
        seg_clean = re.sub(r'[\(\[\*].*?[\)\]\*]', '', seg).strip()
        # Skip the creator name itself as a phrase (it's already in creator_variants)
        if seg_clean.lower() == channel_title.strip().lower():
            continue
        # Skip very short or very long segments and generic terms
        if 4 <= len(seg_clean) <= 60 and seg_clean.lower() not in _GENERIC_SEGMENTS:
            if seg_clean not in distinctive_phrases:
                distinctive_phrases.append(seg_clean)

    # De-duplicate while preserving order
    distinctive_phrases = list(dict.fromkeys(distinctive_phrases))

    # Cleaned tag phrases (lowercase, max 5)
    tag_phrases = [t.strip().lower() for t in tags[:5] if t.strip()]

    # Full text blob for Sentence-BERT encoding
    full_text = " ".join(filter(None, [
        title,
        channel_title,
        " ".join(tags[:5]),
    ]))

    # Parse publish timestamp for date-window filtering
    published_ts: Optional[float] = None
    if yt_published_at:
        try:
            from datetime import datetime, timezone as _tz
            published_ts = datetime.fromisoformat(
                yt_published_at.replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            pass

    return {
        "vid_id": vid_id,
        "url_patterns": url_patterns,
        "creator_variants": creator_variants,
        "topic_words": topic_words,
        "distinctive_phrases": distinctive_phrases,
        "tag_phrases": tag_phrases,
        "title_raw": title,
        "full_text": full_text,
        "published_ts": published_ts,
    }


def _verify_reddit_post_is_about_video(
    post_text: str,
    fingerprint: Dict[str, Any],
) -> tuple[bool, float, str]:
    """
    Gate function — determines whether a Reddit post/comment genuinely refers to
    this specific YouTube video.  Uses three tiers:

    Tier 1 — URL / video-ID match  (score 1.0, tag "url")
        The post body, title, or linked URL explicitly contains the video ID or
        any recognised YouTube URL format for this video.  This covers:
          • Direct YouTube links (youtu.be/..., youtube.com/watch?v=...)
          • Bare video ID embedded anywhere in the text
          • Screenshot posts where the screenshotted URL is present in selftext

    Tier 2 — Creator + distinctive phrase match  (score 0.90, tag "phrase_match")
        Accepted when ALL of the following are true:
          a. The fingerprint has at least one distinctive phrase extracted from the
             title (e.g. text highlighted with *, ", [], () — like *ANARC 2*).
          b. The post text contains at least one creator name variant.
          c. The post text contains at least one of the distinctive phrases.
        This tier is deliberately narrow — it requires BOTH the creator AND a
        distinctive product/event name to be present.  It catches screenshot posts
        and reaction threads that discuss the video without linking its URL.
        Score: 0.90 | Tag: "phrase_match"

    Tier 3 — Strict title word coverage  (score 0.80–0.95, tag "title_match")
        Accepted ONLY when ALL of the following are true:
          a. The post text contains at least one creator name variant.
          b. ≥ 60 % of the video's distinctive title words appear in the text,
             with an absolute minimum of 3 matched words.
             This prevents cross-video collisions: a post about a DIFFERENT video
             by the same creator that only shares a couple of words is rejected.
          c. The video must have ≥ 3 distinctive title words for this tier.
             (Guard lowered from 4 because Tier 2 now handles phrase-rich short titles.)
        Score: 0.80 base + 0.05 per word beyond the minimum 3, capped at 0.95.

    Anything else → rejected (False, 0.0, "none").

    Returns (is_match: bool, confidence_score: float, match_type: str)
    """
    text_lower = post_text.lower()

    # ── Tier 1: Explicit URL / video ID ────────────────────────────────────
    if any(pat.lower() in text_lower for pat in fingerprint["url_patterns"]):
        return True, 1.0, "url"

    creator_variants: List[str] = fingerprint.get("creator_variants", [])
    if not creator_variants:
        return False, 0.0, "none"

    creator_present = any(cv in text_lower for cv in creator_variants if cv)

    # Define safe creator variants (full names or tokens >= 5 chars)
    # Short tokens like "tech" (4 chars) are too generic and would produce false positives
    safe_creator_variants = [
        cv for cv in creator_variants
        if ' ' in cv or len(cv) >= 5
    ]
    safe_creator_present = bool(safe_creator_variants and any(
        cv in text_lower for cv in safe_creator_variants if cv
    ))

    # ── Tier 2: Creator + distinctive phrase ──────────────────────────────
    # e.g. post mentions "Tech Burner" AND "ANARC 2" — very high precision.
    distinctive_phrases: List[str] = fingerprint.get("distinctive_phrases", [])
    if distinctive_phrases and safe_creator_present:
        for phrase in distinctive_phrases:
            if phrase.lower() in text_lower:
                return True, 0.90, "phrase_match"

    # ── Tier 3: Strict title word coverage ───────────────────────────────
    topic_words: List[str] = fingerprint.get("topic_words", [])

    # Need a meaningful title with at least 3 distinctive words
    if not safe_creator_present or len(topic_words) < 3:
        return False, 0.0, "none"

    # Count title words present in the post text
    matched = [w for w in topic_words if w in text_lower]
    coverage = len(matched) / len(topic_words)

    # Require >= 60 % title-word coverage AND at least 3 absolute matches
    if coverage < 0.60 or len(matched) < 3:
        return False, 0.0, "none"

    # Score: 0.80 base + 0.05 per word beyond the minimum 3 (cap at 0.95)
    score = min(0.80 + 0.05 * max(0, len(matched) - 3), 0.95)
    return True, round(score, 3), "title_match"


async def _fetch_reddit_video_discussions(
    vid_id: str,
    title: str = "",
    channel_title: str = "",
    tags: Optional[List[str]] = None,
    yt_published_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search Reddit live (via PRAW) for discussions about a specific YouTube video.

    Matching strategy — three search tiers, all verified through
    ``_verify_reddit_post_is_about_video`` before being accepted:

    Tier 1 — Exact URL / video-ID queries against r/all
        Finds posts that explicitly linked the video.
        Score: 1.0 | Tag: "url"

    Tier 2 — Creator + distinctive-phrase queries  (runs when < 10 posts found)
        For each highlighted phrase in the title (e.g. *ANARC 2* → "ANARC 2"),
        searches Reddit for '"<creator>" "<phrase>"' and '"<creator>" <phrase>'.
        This catches screenshot/image posts where users discuss the video without
        ever linking the YouTube URL.
        Score: 0.90 | Tag: "phrase_match"

    Tier 3 — Quoted video title search  (runs when < 10 posts found)
        Searches Reddit for the literal video title (quoted), with a truncated
        fallback for very long titles.
        Score: 0.80–0.95 | Tag: "title_match"

    Publish-date sanity window:
        Any post created more than 3 days BEFORE the video was uploaded is excluded.
        This prevents old posts about a previous product (e.g. ANARC 1) from
        contaminating results for a new video (e.g. ANARC 2).

    For image / screenshot posts (i.redd.it / i.imgur.com URLs), the top 5
    comments are fetched and appended to the verification text so the gatekeeper
    can confirm the creator and product name are discussed in the thread even when
    they are absent from the post title/body.

    Returns list of dicts with keys: post_id, subreddit, title, selftext, author,
    score, created_utc, permalink, url, match_type, similarity_score, comments.
    """
    from app.services.external.reddit_client import RedditClient
    reddit_client = RedditClient()

    fingerprint = _build_video_fingerprint(vid_id, title, channel_title, tags, yt_published_at)

    # Publish-date window: reject posts created > 3 days before the video upload.
    # 3 days tolerance accounts for pre-launch teasers and time-zone drift.
    published_ts: Optional[float] = fingerprint.get("published_ts")
    _BEFORE_VIDEO_GRACE_DAYS = 3

    def _is_within_date_window(post_created_utc: float) -> bool:
        """Return True if the post timestamp is within acceptable range."""
        if published_ts is None:
            return True  # no date info — allow everything
        earliest_allowed = published_ts - _BEFORE_VIDEO_GRACE_DAYS * 86400
        return post_created_utc >= earliest_allowed

    # Image-hosting domains whose posts should include top-comment context
    _IMAGE_HOSTS = ("i.redd.it", "i.imgur.com", "preview.redd.it")

    def _build_post_verification_text(
        s,  # praw.models.Submission
        include_comments: bool = False,
    ) -> str:
        """Concatenate post URL, selftext, and title (+ optional top comments)."""
        parts = [
            getattr(s, 'url', '') or '',
            getattr(s, 'selftext', '') or '',
            getattr(s, 'title', '') or '',
        ]
        if include_comments:
            try:
                s.comments.replace_more(limit=0)
                for c in s.comments[:10]:
                    body = getattr(c, 'body', '') or ''
                    if body.strip() and body.strip() not in {"[deleted]", "[removed]"}:
                        parts.append(body)
            except Exception:
                pass
        return " ".join(filter(None, parts))

    def _is_image_post(s) -> bool:
        url = getattr(s, 'url', '') or ''
        return any(host in url for host in _IMAGE_HOSTS)

    def _try_add_post(
        s,
        seen_posts: Dict[str, tuple],
        *,
        allow_negative_score: bool = False,
    ) -> None:
        """Verify a submission and add it to seen_posts if it passes the gate."""
        if s.id in seen_posts:
            return
        if _SPAM_SUB_RE.search(str(s.subreddit)):
            return
        if not allow_negative_score and s.score < 0:
            return
        if not _is_within_date_window(s.created_utc):
            return
        # For image/screenshot posts also include top comments in verification
        is_img = _is_image_post(s)
        post_text = _build_post_verification_text(s, include_comments=is_img)
        is_match, score, tag = _verify_reddit_post_is_about_video(post_text, fingerprint)
        if is_match:
            seen_posts[s.id] = (s, tag, score)

    def _search_reddit_sync() -> List[Dict[str, Any]]:
        seen_posts: Dict[str, tuple] = {}  # post_id -> (submission, match_type, score)

        # ── Tier 1: Exact URL / ID queries ───────────────────────────────────
        url_queries = [
            f"url:youtu.be/{vid_id}",
            f"url:youtube.com/watch?v={vid_id}",
            vid_id,
        ]
        for q in url_queries:
            try:
                for s in reddit_client._reddit.subreddit("all").search(
                    query=q, sort="relevance", limit=15
                ):
                    _try_add_post(s, seen_posts, allow_negative_score=True)
            except Exception:
                pass

        # ── Tier 2: Creator + distinctive-phrase queries ──────────────────────
        # e.g. searches '"Tech Burner" "ANARC 2"' and '"Tech Burner" ANARC 2'
        # Catches screenshot posts and reaction threads that don't include a URL.
        distinctive_phrases: List[str] = fingerprint.get("distinctive_phrases", [])
        creator_variants: List[str] = fingerprint.get("creator_variants", [])
        safe_creator_variants = [
            cv for cv in creator_variants
            if ' ' in cv or len(cv) >= 5
        ]
        # Use channel_title as primary, but also include safe aliases
        query_creators = [channel_title.strip()] if channel_title else []
        query_creators.extend([cv for cv in safe_creator_variants if cv.lower() != channel_title.lower().strip()])
        # Cap at 2 creator terms to prevent query explosion
        query_creators = query_creators[:2]

        if distinctive_phrases and query_creators and len(seen_posts) < 10:
            phrase_queries: List[str] = []
            for phrase in distinctive_phrases[:3]:  # cap at 3 phrases
                for creator_term in query_creators:
                    # Quoted phrase (exact)
                    phrase_queries.append(f'"{creator_term}" "{phrase}"')
                    # Unquoted phrase (broader)
                    phrase_queries.append(f'"{creator_term}" {phrase}')
            # De-duplicate
            phrase_queries = list(dict.fromkeys(phrase_queries))

            for q in phrase_queries:
                if len(seen_posts) >= 10:
                    break
                try:
                    for s in reddit_client._reddit.subreddit("all").search(
                        query=q, sort="relevance", limit=15
                    ):
                        _try_add_post(s, seen_posts)
                except Exception:
                    pass

        # ── Tier 3: Quoted video title search ────────────────────────────────
        # Searches Reddit for the actual video title (quoted), catching posts
        # that discuss the video by name without linking it.
        title_raw: str = fingerprint.get("title_raw", "")
        if title_raw and len(seen_posts) < 10:
            title_queries: List[str] = [f'"{title_raw}"']

            # Fallback: if the title is very long, also try a truncated version
            # of the first 60 chars to account for Reddit's search tokenisation
            if len(title_raw) > 60:
                truncated = title_raw[:60].rsplit(" ", 1)[0]  # cut at word boundary
                if len(truncated) >= 20:
                    title_queries.append(f'"{truncated}"')

            for q in title_queries:
                if len(seen_posts) >= 10:
                    break
                try:
                    for s in reddit_client._reddit.subreddit("all").search(
                        query=q, sort="relevance", limit=15
                    ):
                        _try_add_post(s, seen_posts)
                except Exception:
                    pass

        # ── Extract top comments from each matched post ──────────────────────
        results: List[Dict[str, Any]] = []
        for post, match_type, sim_score in seen_posts.values():
            try:
                post.comments.replace_more(limit=0)
                top_comments: List[Dict[str, Any]] = []
                for c in post.comments[:10]:
                    if not hasattr(c, "body") or not c.body:
                        continue
                    body_strip = c.body.strip()
                    author_name = str(c.author) if c.author else "[deleted]"
                    if author_name.lower() in {"automoderator", "[deleted]"}:
                        continue
                    if body_strip in {"[deleted]", "[removed]"}:
                        continue
                    if len(body_strip) < 5:
                        continue
                    top_comments.append({
                        "id": c.id,
                        "author": author_name,
                        "body": body_strip,
                        "score": c.score,
                        "created_utc": c.created_utc,
                        "permalink": f"https://reddit.com{c.permalink}",
                    })
                results.append({
                    "post_id": post.id,
                    "subreddit": str(post.subreddit),
                    "title": post.title,
                    "selftext": post.selftext or "",
                    "author": str(post.author) if post.author else "[deleted]",
                    "score": post.score,
                    "num_comments": getattr(post, 'num_comments', 0),
                    "created_utc": post.created_utc,
                    "permalink": f"https://reddit.com{post.permalink}",
                    "url": getattr(post, 'url', ''),
                    "match_type": match_type,
                    "similarity_score": sim_score,
                    "comments": top_comments,
                })
            except Exception:
                pass
        return results

    return await reddit_client._run_in_thread(_search_reddit_sync)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get(
    "/shared-videos",
    response_model=List[SharedVideoItem],
    summary="YouTube videos found shared inside Reddit threads with discussion drill-down and timestamps",
)
async def get_shared_videos(
    subreddit_name: Optional[str] = Query(
        default=None,
        description="The subreddit to scan for YouTube links (or leave blank to scan all subreddits)",
    ),
    video_url_or_id: Optional[str] = Query(
        default=None,
        description="Optional YouTube video URL or ID to filter discussions for",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=2000,
        description="Number of Reddit comments to scan (min 1 for global recently-tracked queries)",
    ),
) -> List[SharedVideoItem]:
    """
    Scans up to *limit* Reddit comments for YouTube video URLs.
    Extracts full discussion threads, computes propagation timeline and delay,
    sentiment breakdown on both YouTube and Reddit, and topic keywords.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError
    import asyncio as _asyncio

    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # 1. Fetch Reddit comment bodies with full discussion metadata
    query_filter: Dict[str, Any] = {"platform": "reddit"}
    if subreddit_name:
        clean_sub = subreddit_name.strip().lstrip("/").replace("r/", "").replace("/r/", "").strip().lower()
        query_filter["parent_id"] = {"$regex": f"^{re.escape(clean_sub)}$", "$options": "i"}

    cursor = (
        comments_coll
        .find(
            query_filter,
            {
                "_id": 0,
                "platform_id": 1,
                "body": 1,
                "author": 1,
                "score": 1,
                "published_at": 1,
                "permalink": 1,
                "parent_id": 1,
                "post_id": 1,
                "sentiment_label": 1,
                "sentiment_score": 1,
            },
        )
        .sort("ingested_at", -1)
        .limit(limit)
    )
    reddit_docs = await cursor.to_list(length=limit)

    if not reddit_docs:
        return []

    target_vid_id = _extract_video_id(video_url_or_id) if video_url_or_id else None

    # 2A. Regex URL matching (fast-path)
    video_to_discussions: Dict[str, List[Dict[str, Any]]] = {}
    matched_comment_keys: set = set()

    for doc in reddit_docs:
        body = doc.get("body", "")
        matches = _YT_URL_RE.findall(body)
        for vid_id in set(matches):
            if target_vid_id and vid_id != target_vid_id:
                continue
            doc_copy = dict(doc)
            doc_copy["match_type"] = "url"
            doc_copy["similarity_score"] = 1.0
            video_to_discussions.setdefault(vid_id, []).append(doc_copy)
            c_key = doc.get("platform_id") or doc.get("permalink") or body
            matched_comment_keys.add(c_key)

    # 2B. Semantic Similarity Matching (Sentence-BERT fallback & supplement)
    # Collect candidate YouTube videos to compare Reddit discussions against
    candidate_videos_map: Dict[str, Dict[str, Any]] = {}

    if target_vid_id:
        target_payload = await payloads_coll.find_one(
            {"platform": "youtube", "platform_id": target_vid_id},
            {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1},
        )
        if target_payload:
            candidate_videos_map[target_vid_id] = target_payload
        else:
            candidate_videos_map[target_vid_id] = {"platform_id": target_vid_id, "title": target_vid_id}
    else:
        # Load indexed YouTube videos from MongoDB payloads (up to 50 videos)
        cand_cursor = payloads_coll.find(
            {"platform": "youtube"},
            {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1},
        ).sort("ingested_at", -1).limit(50)
        cand_docs = await cand_cursor.to_list(length=50)
        for c_doc in cand_docs:
            c_id = c_doc.get("platform_id")
            if c_id:
                candidate_videos_map[c_id] = c_doc

        # Also register any video IDs that were already discovered via URL
        for v_id in list(video_to_discussions.keys()):
            if v_id not in candidate_videos_map:
                candidate_videos_map[v_id] = {"platform_id": v_id, "title": v_id}

    # Filter Reddit comments that did not match via URL
    unmatched_reddit_docs = [
        d for d in reddit_docs
        if (d.get("platform_id") or d.get("permalink") or d.get("body")) not in matched_comment_keys
    ]

    if candidate_videos_map and unmatched_reddit_docs:
        from app.services.analytics.semantic_matcher import get_semantic_matcher
        from app.core.config import get_settings
        current_settings = get_settings()

        matcher = get_semantic_matcher()
        candidate_list = list(candidate_videos_map.values())
        sem_matches = matcher.match_discussions_to_videos(
            unmatched_reddit_docs,
            candidate_list,
            threshold=current_settings.SEMANTIC_SIMILARITY_THRESHOLD,
        )

        for matched_vid, items in sem_matches.items():
            if target_vid_id and matched_vid != target_vid_id:
                continue
            for disc_doc, score in items:
                d_copy = dict(disc_doc)
                d_copy["match_type"] = "semantic"
                d_copy["similarity_score"] = score
                video_to_discussions.setdefault(matched_vid, []).append(d_copy)

    if not video_to_discussions:
        return []

    all_video_ids = list(video_to_discussions.keys())

    # 3. Fetch YouTube payload snapshots from MongoDB for matched video IDs
    yt_cursor = payloads_coll.find(
        {"platform": "youtube", "platform_id": {"$in": all_video_ids}},
        {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1, "ingested_at": 1},
    )
    yt_docs = await yt_cursor.to_list(length=len(all_video_ids))
    yt_cached: Dict[str, Dict] = {d["platform_id"]: d for d in yt_docs}

    # 4. For video IDs missing or lacking metadata, fetch live from YouTube Data API
    missing_ids = [vid for vid in all_video_ids if vid not in yt_cached]
    yt_live_meta: Dict[str, Any] = {}

    if missing_ids:
        try:
            yt_client = YouTubeClient()
            chunk_size = 50

            async def _fetch_batch(ids: List[str]) -> dict:
                request = yt_client._service.videos().list(
                    part="snippet,statistics",
                    id=",".join(ids),
                )
                data = await _asyncio.to_thread(request.execute)
                result = {}
                for item in data.get("items", []):
                    vid = item.get("id", "")
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    thumbnails = snippet.get("thumbnails", {})
                    thumb = (
                        thumbnails.get("high", {}).get("url")
                        or thumbnails.get("medium", {}).get("url")
                        or thumbnails.get("default", {}).get("url")
                    )
                    result[vid] = {
                        "title": snippet.get("title", ""),
                        "channel_title": snippet.get("channelTitle", ""),
                        "thumbnail_url": thumb,
                        "published_at": snippet.get("publishedAt"),
                        "tags": snippet.get("tags", []),
                        "views": int(stats.get("viewCount", 0) or 0),
                        "likes": int(stats.get("likeCount", 0) or 0),
                        "comment_count": int(stats.get("commentCount", 0) or 0),
                    }
                return result

            chunks = [missing_ids[i:i + chunk_size] for i in range(0, len(missing_ids), chunk_size)]
            chunk_results = await _asyncio.gather(*[_fetch_batch(chunk) for chunk in chunks], return_exceptions=True)
            for res in chunk_results:
                if isinstance(res, dict):
                    yt_live_meta.update(res)

        except YouTubeAPIError:
            pass
        except Exception:
            pass

    # 5. Fetch Reddit post-level statistics
    all_post_ids = list({
        d.get("post_id") or d.get("platform_id")
        for docs in video_to_discussions.values()
        for d in docs
        if d.get("post_id") or d.get("platform_id")
    })
    reddit_post_cursor = payloads_coll.find(
        {"platform": "reddit", "platform_id": {"$in": all_post_ids}},
        {"_id": 0, "platform_id": 1, "stats": 1},
    )
    reddit_post_docs = await reddit_post_cursor.to_list(length=len(all_post_ids))
    reddit_post_stats: Dict[str, Dict] = {
        d["platform_id"]: d.get("stats", {}) for d in reddit_post_docs
    }

    # 6. Fetch YouTube comments sentiment for cached videos
    # NOTE: YouTube comments are stored with parent_id=channel_id and the
    # video in video_id — so match on video_id (parent_id only as a legacy
    # fallback for docs that lack video_id).
    yt_comments_cursor = comments_coll.find(
        {
            "platform": "youtube",
            "$or": [{"video_id": {"$in": all_video_ids}}, {"parent_id": {"$in": all_video_ids}}],
        },
        {"_id": 0, "video_id": 1, "parent_id": 1, "sentiment_label": 1},
    )
    yt_comments_docs = await yt_comments_cursor.to_list(length=1000)
    yt_comments_by_vid: Dict[str, List[str]] = {}
    _vid_set = set(all_video_ids)
    for cd in yt_comments_docs:
        lbl = cd.get("sentiment_label")
        if not lbl:
            continue
        vid = cd.get("video_id") or None
        if vid not in _vid_set:
            # Legacy doc without video_id whose parent_id happens to be a video ID
            legacy_parent = cd.get("parent_id")
            vid = legacy_parent if legacy_parent in _vid_set else None
        if vid:
            yt_comments_by_vid.setdefault(vid, []).append(lbl)

    # 7. Process sentiment service for any Reddit comments that haven't been labeled yet
    unlabeled_bodies = [
        d.get("body", "")
        for docs in video_to_discussions.values()
        for d in docs
        if not d.get("sentiment_label") and d.get("body")
    ]
    quick_sentiment_map: Dict[str, str] = {}
    if unlabeled_bodies:
        try:
            svc = _get_sentiment_svc()
            batch_res = await _asyncio.to_thread(svc.analyze_batch, unlabeled_bodies[:100])
            for text, res in zip(unlabeled_bodies[:100], batch_res):
                quick_sentiment_map[text] = res.label.value
        except Exception:
            pass

    # 8. Assemble enriched SharedVideoItems
    shared: List[SharedVideoItem] = []

    for vid_id, raw_discussions in video_to_discussions.items():
        cached_yt = yt_cached.get(vid_id, {})
        live_yt = yt_live_meta.get(vid_id, {})

        cached_stats = cached_yt.get("stats", {})
        views = cached_stats.get("views") or live_yt.get("views")
        likes = cached_stats.get("likes") or live_yt.get("likes")
        comment_count = live_yt.get("comment_count")
        title = cached_yt.get("title") or live_yt.get("title")
        thumbnail_url = live_yt.get("thumbnail_url")
        channel_title = live_yt.get("channel_title")
        ing_at = cached_yt.get("ingested_at")
        ing_at_str = ing_at.isoformat() if hasattr(ing_at, "isoformat") else (str(ing_at) if ing_at else None)
        yt_published_at = live_yt.get("published_at") or ing_at_str
        yt_tags = live_yt.get("tags", [])

        # Build Reddit discussions list
        reddit_discussions: List[RedditDiscussionItem] = []
        reddit_sentiments: List[str] = []
        discussion_dates: List[datetime] = []
        subreddits_set = set()
        post_ids_set = set()
        reddit_upvotes_total = 0
        reddit_comments_total = 0

        for r_doc in raw_discussions:
            sub = r_doc.get("parent_id") or subreddit_name or ""
            if sub:
                subreddits_set.add(sub)
            p_id = r_doc.get("post_id") or r_doc.get("platform_id") or ""
            if p_id:
                post_ids_set.add(p_id)

            score = int(r_doc.get("score") or 0)
            reddit_upvotes_total += score

            pub_str = r_doc.get("published_at")
            pub_dt = _parse_iso_datetime(pub_str)
            if pub_dt:
                discussion_dates.append(pub_dt)

            label = r_doc.get("sentiment_label")
            if not label:
                label = quick_sentiment_map.get(r_doc.get("body", ""), "neutral")
            reddit_sentiments.append(label)

            reddit_discussions.append(
                RedditDiscussionItem(
                    discussion_id=r_doc.get("platform_id", ""),
                    post_id=p_id,
                    subreddit=sub,
                    author=r_doc.get("author") or "[deleted]",
                    body=r_doc.get("body", ""),
                    score=score,
                    published_at=pub_str,
                    permalink=r_doc.get("permalink"),
                    sentiment_label=label,
                    sentiment_score=r_doc.get("sentiment_score"),
                    match_type=r_doc.get("match_type", "url"),
                    similarity_score=r_doc.get("similarity_score"),
                )
            )

        # Include parent post stats if available
        for p_id in post_ids_set:
            p_stat = reddit_post_stats.get(p_id, {})
            reddit_comments_total += int(p_stat.get("comments", 0) or 0)

        # Timestamps & Propagation analysis
        first_shared_dt = min(discussion_dates) if discussion_dates else None
        latest_shared_dt = max(discussion_dates) if discussion_dates else None
        first_shared_str = first_shared_dt.isoformat() if first_shared_dt else None
        latest_shared_str = latest_shared_dt.isoformat() if latest_shared_dt else None

        yt_pub_dt = _parse_iso_datetime(yt_published_at)
        propagation_delay_hours: Optional[float] = None
        propagation_speed: Optional[str] = None

        if yt_pub_dt and first_shared_dt:
            diff_sec = (first_shared_dt - yt_pub_dt).total_seconds()
            delay_h = max(0.0, round(diff_sec / 3600.0, 1))
            propagation_delay_hours = delay_h

            if delay_h <= 6.0:
                propagation_speed = "Rapid (< 6h)"
            elif delay_h <= 24.0:
                propagation_speed = "Moderate (6-24h)"
            elif delay_h <= 72.0:
                propagation_speed = "Delayed (1-3d)"
            else:
                propagation_speed = f"Archival ({int(delay_h // 24)}d lag)"
        elif first_shared_dt:
            propagation_speed = "Recent Community Discovery"

        # Sentiment breakdown for both platforms — measured comments only.
        # No like-ratio heuristic: without YouTube comments for this video we
        # return an empty breakdown so the dashboard shows "insufficient data"
        # instead of fabricated numbers.
        rd_sentiment = _compute_sentiment_breakdown(reddit_sentiments)

        yt_labels = yt_comments_by_vid.get(vid_id, [])
        yt_sentiment = (
            _compute_sentiment_breakdown(yt_labels) if yt_labels else _empty_breakdown()
        )

        # Sentiment disparity note — only meaningful when both sides measured.
        gap = _sentiment_gap(yt_sentiment, rd_sentiment)
        if not _has_samples(yt_sentiment) or not _has_samples(rd_sentiment):
            if _has_samples(rd_sentiment):
                disparity_note = (
                    f"Reddit discussion sentiment is {int(rd_sentiment.positive * 100)}% positive "
                    f"({rd_sentiment.sample_size} comments analyzed). "
                    "No YouTube comments for this video have been ingested yet — "
                    "analyze the video above for a full YouTube-vs-Reddit comparison."
                )
            elif _has_samples(yt_sentiment):
                disparity_note = (
                    f"YouTube audience sentiment is {int(yt_sentiment.positive * 100)}% positive "
                    f"({yt_sentiment.sample_size} comments analyzed). "
                    "No Reddit discussions found for this video yet."
                )
            else:
                disparity_note = "No sentiment comments found for this video yet."
        elif gap >= 0.20:
            disparity_note = f"YouTube audience response is {int(gap * 100)}% more positive than the Reddit discussion."
        elif gap <= -0.20:
            disparity_note = f"Reddit discussion is {int(abs(gap) * 100)}% more positive than YouTube reception."
        else:
            disparity_note = "Audience sentiment is broadly consistent across YouTube and Reddit."

        # Topics extraction (combining tags + discussion text)
        discussion_texts = [d.body for d in reddit_discussions]
        reddit_topics = _extract_topics_from_texts(discussion_texts, top_n=4)
        combined_topics = list(dict.fromkeys(yt_tags[:4] + reddit_topics))

        # Determine overall match_type and max_similarity
        types = {d.get("match_type", "url") for d in raw_discussions}
        if "url" in types and "semantic" in types:
            overall_match_type = "hybrid"
        elif "semantic" in types:
            overall_match_type = "semantic"
        else:
            overall_match_type = "url"

        scores = [d.get("similarity_score") for d in raw_discussions if d.get("similarity_score") is not None]
        max_sim = max(scores) if scores else (1.0 if overall_match_type == "url" else None)

        shared.append(
            SharedVideoItem(
                youtube_video_id=vid_id,
                youtube_url=f"https://www.youtube.com/watch?v={vid_id}",
                reddit_post_ids=list(post_ids_set),
                reddit_subreddits=list(subreddits_set) if subreddits_set else ([subreddit_name] if subreddit_name else []),
                total_reddit_shares=len(reddit_discussions),
                youtube_views=views,
                youtube_likes=likes,
                youtube_comment_count=comment_count,
                youtube_title=title,
                youtube_thumbnail_url=thumbnail_url,
                youtube_channel_title=channel_title,
                youtube_published_at=yt_published_at,
                youtube_tags=yt_tags[:6],
                youtube_sentiment=yt_sentiment,
                reddit_total_upvotes=reddit_upvotes_total or None,
                reddit_total_comments=reddit_comments_total or len(reddit_discussions) or None,
                reddit_first_shared_at=first_shared_str,
                reddit_latest_shared_at=latest_shared_str,
                propagation_delay_hours=propagation_delay_hours,
                propagation_speed=propagation_speed,
                reddit_sentiment=rd_sentiment,
                sentiment_disparity_note=disparity_note,
                reddit_discussions=reddit_discussions,
                topics=combined_topics[:6],
                match_type=overall_match_type,
                similarity_score=max_sim,
            )
        )

    # Sort: subreddit-scoped → by total Reddit shares desc then YouTube views.
    # Global (no subreddit filter) → by most recently ingested first so that
    # the "recently tracked" chips on the frontend show the latest videos.
    if subreddit_name:
        shared.sort(key=lambda x: (x.total_reddit_shares, x.youtube_views or 0), reverse=True)
    else:
        # Keep insertion order (already sorted by ingested_at desc from cursor)
        pass
    return shared


@router.get(
    "/video-engagement",
    response_model=VideoCrossPlatformEngagementResponse,
    summary="Get cross-platform engagement for a specific YouTube video across Reddit",
)
async def get_video_engagement(
    video_url_or_id: str = Query(
        ...,
        description="YouTube video URL or 11-character Video ID",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"],
    ),
    comment_scan_limit: int = Query(
        default=2000,
        ge=50,
        le=5000,
        description="Number of Reddit comments to scan for mentions",
    ),
) -> VideoCrossPlatformEngagementResponse:
    """
    Given a YouTube Video URL or Video ID:
    1. Extracts canonical YouTube Video ID.
    2. Fetches YouTube video metadata (views, likes, comments, title, channel, thumbnail).
    3. Scans all Reddit discussions across all subreddits in MongoDB referencing this video.
    4. Computes cross-platform metrics:
       - Subreddits Discussing count (number of distinct subreddits) and list.
       - Total Reddit discussions/mentions citing the video.
       - Total Reddit upvotes and comments.
       - Propagation timeline and speed.
       - Sentiment comparison between YouTube and Reddit.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError
    import asyncio as _asyncio

    vid_id = _extract_video_id(video_url_or_id)
    if not vid_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid YouTube video URL or 11-character video ID is required.",
        )

    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # 1. Fetch YouTube video metadata from MongoDB cache or live YouTube Data API
    yt_payload = await payloads_coll.find_one(
        {"platform": "youtube", "platform_id": vid_id},
        {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1, "ingested_at": 1},
    )

    title = (yt_payload or {}).get("title") if yt_payload else None
    stats = (yt_payload or {}).get("stats", {}) if yt_payload else {}
    views = stats.get("views")
    likes = stats.get("likes")
    comment_count = stats.get("comment_count")
    thumbnail_url = None
    channel_title = None
    yt_ing_at = yt_payload.get("ingested_at") if yt_payload else None
    yt_published_at = (
        yt_ing_at.isoformat() if hasattr(yt_ing_at, "isoformat") else (str(yt_ing_at) if yt_ing_at else None)
    )
    yt_tags: List[str] = []

    # If missing full details, query YouTube Data API v3 live
    try:
        yt_client = YouTubeClient()
        req = yt_client._service.videos().list(part="snippet,statistics", id=vid_id)
        yt_data = await _asyncio.to_thread(req.execute)
        items = yt_data.get("items", [])
        if items:
            item = items[0]
            snippet = item.get("snippet", {})
            st = item.get("statistics", {})
            title = snippet.get("title") or title
            channel_title = snippet.get("channelTitle")
            thumbnails = snippet.get("thumbnails", {})
            thumbnail_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            yt_published_at = snippet.get("publishedAt") or yt_published_at
            yt_tags = snippet.get("tags", [])
            views = int(st.get("viewCount", views or 0) or 0)
            likes = int(st.get("likeCount", likes or 0) or 0)
            comment_count = int(st.get("commentCount", comment_count or 0) or 0)
    except Exception:
        pass

    canonical_yt_url = f"https://www.youtube.com/watch?v={vid_id}"

    # 2. Fetch Reddit discussions: search local MongoDB AND search Reddit live via PRAW
    # Matching uses two tiers:
    #   Tier 1 (url)        — post body explicitly contains this video's URL or bare ID.
    #   Tier 2 (contextual) — post mentions the creator by name AND ≥ 2 distinctive title
    #                         keywords, but does NOT contain the URL.  This captures
    #                         discussions that reference the video by content rather than
    #                         by link, while still being strictly tied to THIS video.

    matched_discussions: List[Dict[str, Any]] = []
    seen_discussion_ids: set = set()

    scan_limit = comment_scan_limit if isinstance(comment_scan_limit, int) else 2000

    # Build the video fingerprint once — reused for all verification calls
    video_fp = _build_video_fingerprint(
        vid_id=vid_id,
        title=title or "",
        channel_title=channel_title or "",
        tags=yt_tags or [],
        yt_published_at=yt_published_at,
    )

    # 2A. Search local MongoDB cached Reddit comments
    reddit_cursor = (
        comments_coll
        .find(
            {"platform": "reddit"},
            {
                "_id": 0,
                "platform_id": 1,
                "body": 1,
                "author": 1,
                "score": 1,
                "published_at": 1,
                "permalink": 1,
                "parent_id": 1,
                "post_id": 1,
                "sentiment_label": 1,
                "sentiment_score": 1,
            },
        )
        .sort("ingested_at", -1)
        .limit(scan_limit)
    )
    all_reddit_docs = await reddit_cursor.to_list(length=scan_limit)

    for doc in all_reddit_docs:
        body = doc.get("body") or ""
        if not body:
            continue
        d_id = doc.get("platform_id")
        if not d_id or d_id in seen_discussion_ids:
            continue

        is_match, score, tag = _verify_reddit_post_is_about_video(body, video_fp)
        if is_match:
            seen_discussion_ids.add(d_id)
            d_copy = dict(doc)
            d_copy["match_type"] = tag
            d_copy["similarity_score"] = score
            matched_discussions.append(d_copy)

    # 2B. Live Reddit search via PRAW (all three tiers inside _fetch_reddit_video_discussions)
    # live_post_stats tracks each matched Reddit post thread separately so we can
    # surface accurate per-post counts (num_comments, score) in the KPIs.
    live_post_stats: Dict[str, Dict[str, Any]] = {}  # post_id -> {subreddit, score, num_comments}

    try:
        live_reddit_posts = await _fetch_reddit_video_discussions(
            vid_id=vid_id,
            title=title or "",
            channel_title=channel_title or "",
            tags=yt_tags or [],
            yt_published_at=yt_published_at,
        )

        for p in live_reddit_posts:
            p_match_type = p.get("match_type", "url")
            p_sim_score = p.get("similarity_score", 1.0)
            p_id = p["post_id"]

            # Track post-level stats (unique per post_id)
            if p_id not in live_post_stats:
                live_post_stats[p_id] = {
                    "subreddit": p["subreddit"],
                    "score": p["score"],
                    "num_comments": p.get("num_comments", 0),
                }

            # Add top comments from this post as discussion items
            for c in p.get("comments", []):
                c_id = c["id"]
                if c_id not in seen_discussion_ids:
                    seen_discussion_ids.add(c_id)
                    pub_iso = datetime.fromtimestamp(c["created_utc"], tz=timezone.utc).isoformat() if c.get("created_utc") else None
                    matched_discussions.append({
                        "platform_id": c_id,
                        "post_id": p_id,
                        "parent_id": p["subreddit"],
                        "author": c["author"],
                        "body": c["body"],
                        "score": c["score"],
                        "published_at": pub_iso,
                        "permalink": c["permalink"],
                        "match_type": p_match_type,
                        "similarity_score": p_sim_score,
                        "sentiment_label": None,
                        "sentiment_score": None,
                        "_is_post": False,
                    })

            # Do NOT include the post thread itself as a discussion body item
            # (it inflates comment count stats and the title is not a comment).
            # Post-level info is tracked in live_post_stats above.
    except Exception:
        pass

    # 2C. Persist verified live discussions so DB coverage grows with usage.
    # Live PRAW results arrive without sentiment labels; insert-only writes
    # ($setOnInsert) mean repeat queries hit Mongo instead of re-burning
    # Reddit/YouTube quota — and existing docs (with sentiment labels) are
    # never clobbered.
    if matched_discussions:
        try:
            from pymongo import UpdateOne as _UpdateOne

            _persist_ops = []
            _now = datetime.now(timezone.utc)
            for _d in matched_discussions:
                _pid = _d.get("platform_id")
                if not _pid or not _d.get("body"):
                    continue
                _persist_ops.append(
                    _UpdateOne(
                        {"platform": "reddit", "platform_id": _pid},
                        {
                            "$setOnInsert": {
                                "platform": "reddit",
                                "platform_id": _pid,
                                "parent_id": str(_d.get("parent_id") or "").lower(),
                                "post_id": _d.get("post_id") or _pid,
                                "author": _d.get("author") or "[deleted]",
                                "body": _d.get("body") or "",
                                "score": int(_d.get("score") or 0),
                                "published_at": _d.get("published_at"),
                                "permalink": _d.get("permalink"),
                                "match_type": _d.get("match_type"),
                                "similarity_score": _d.get("similarity_score"),
                                "sentiment_processed": False,
                                "ingested_at": _now,
                            }
                        },
                        upsert=True,
                    )
                )
            if _persist_ops:
                await comments_coll.bulk_write(_persist_ops, ordered=False)
        except Exception:
            pass

    # 3. Analyze Reddit discussions
    reddit_discussions: List[RedditDiscussionItem] = []
    reddit_sentiments: List[str] = []
    discussion_dates: List[datetime] = []
    subreddits_set = set()
    post_ids_set = set()
    reddit_upvotes_total = 0
    # reddit_total_comments_sum = sum of actual num_comments on each matched Reddit post
    reddit_total_comments_sum = 0
    discussion_bodies: List[str] = []

    # Collect subreddits and upvotes from live matched posts
    for p_id, p_stat in live_post_stats.items():
        sub = (p_stat.get("subreddit") or "").lower()
        if sub:
            subreddits_set.add(sub)
        post_ids_set.add(p_id)
        reddit_upvotes_total += int(p_stat.get("score") or 0)
        reddit_total_comments_sum += int(p_stat.get("num_comments") or 0)

    # Also sweep MongoDB matched discussions for subreddits/post IDs from the DB scan
    for r_doc in matched_discussions:
        sub = (r_doc.get("parent_id") or "").lower()
        if sub:
            subreddits_set.add(sub)
        p_id = r_doc.get("post_id") or r_doc.get("platform_id") or ""
        if p_id and p_id not in post_ids_set:
            # This post was found from MongoDB scan but not from PRAW live search;
            # we don't have num_comments for it, so skip double-counting upvotes.
            post_ids_set.add(p_id)

    # Run sentiment classification on ALL unlabelled discussion bodies in one batch.
    # This must happen AFTER matched_discussions is fully assembled (MongoDB + live PRAW),
    # so live PRAW comments (which always arrive without a sentiment_label) get real
    # classification instead of silently defaulting to "neutral".
    unlabeled_bodies = [
        d.get("body", "")
        for d in matched_discussions
        if not d.get("sentiment_label") and d.get("body")
    ]
    quick_sentiment_map: Dict[str, tuple[str, float]] = {}
    if unlabeled_bodies:
        try:
            svc = _get_sentiment_svc()
            # Process up to 500 Reddit bodies in the first batch for a larger Reddit sample.
            batch_input = unlabeled_bodies[:500]
            batch_res = await _asyncio.to_thread(svc.analyze_batch, batch_input)
            for text, res in zip(batch_input, batch_res):
                quick_sentiment_map[text] = (res.label.value, res.score)
        except Exception:
            pass

    # Overflow batch for bodies 500–750 — still off the event loop via to_thread.
    _overflow_bodies = [t for t in unlabeled_bodies[500:750] if t not in quick_sentiment_map]
    if _overflow_bodies:
        try:
            svc = _get_sentiment_svc()
            _overflow_res = await _asyncio.to_thread(svc.analyze_batch, _overflow_bodies)
            for text, res in zip(_overflow_bodies, _overflow_res):
                quick_sentiment_map[text] = (res.label.value, res.score)
        except Exception:
            pass

    for r_doc in matched_discussions:
        pub_str = r_doc.get("published_at")
        pub_dt = _parse_iso_datetime(pub_str)
        if pub_dt:
            discussion_dates.append(pub_dt)

        label = r_doc.get("sentiment_label")
        s_score = r_doc.get("sentiment_score")
        if not label:
            body_text = r_doc.get("body", "")
            mapped = quick_sentiment_map.get(body_text)
            if mapped:
                label, s_score = mapped
            else:
                # Only reachable past the 250-item classification cap or for
                # blank bodies — default honestly instead of blocking inference.
                label, s_score = "neutral", 0.5
        reddit_sentiments.append(label)
        if r_doc.get("body"):
            discussion_bodies.append(r_doc["body"])

        sub = (r_doc.get("parent_id") or "").lower()
        p_id = r_doc.get("post_id") or r_doc.get("platform_id") or ""
        score = int(r_doc.get("score") or 0)

        reddit_discussions.append(
            RedditDiscussionItem(
                discussion_id=r_doc.get("platform_id", ""),
                post_id=p_id,
                subreddit=sub,
                author=r_doc.get("author") or "[deleted]",
                body=r_doc.get("body", ""),
                score=score,
                published_at=pub_str,
                permalink=r_doc.get("permalink"),
                sentiment_label=label,
                sentiment_score=s_score,
                match_type=r_doc.get("match_type", "url"),
                similarity_score=r_doc.get("similarity_score", 1.0),
            )
        )

    # Sort all discussions by score descending, keep top 10 for the UI card
    reddit_discussions.sort(key=lambda d: d.score, reverse=True)
    top_discussions = reddit_discussions[:10]

    # 4. Propagation timeline
    first_shared_dt = min(discussion_dates) if discussion_dates else None
    latest_shared_dt = max(discussion_dates) if discussion_dates else None
    first_shared_str = first_shared_dt.isoformat() if first_shared_dt else None
    latest_shared_str = latest_shared_dt.isoformat() if latest_shared_dt else None

    yt_pub_dt = _parse_iso_datetime(yt_published_at)
    propagation_delay_hours: Optional[float] = None
    propagation_speed: Optional[str] = None

    if yt_pub_dt and first_shared_dt:
        diff_sec = (first_shared_dt - yt_pub_dt).total_seconds()
        delay_h = max(0.0, round(diff_sec / 3600.0, 1))
        propagation_delay_hours = delay_h
        if delay_h <= 6.0:
            propagation_speed = "Rapid (< 6h)"
        elif delay_h <= 24.0:
            propagation_speed = "Moderate (6-24h)"
        elif delay_h <= 72.0:
            propagation_speed = "Delayed (1-3d)"
        else:
            propagation_speed = f"Archival ({int(delay_h // 24)}d lag)"
    elif first_shared_dt:
        propagation_speed = "Community Discovered"

    # 5. YouTube sentiment — from MongoDB first, then live YouTube API fallback
    # Use a large sample (500) to get a statistically meaningful sentiment signal.
    yt_comments_cursor = comments_coll.find(
        {"platform": "youtube", "$or": [{"video_id": vid_id}, {"parent_id": vid_id}]},
        {"_id": 0, "sentiment_label": 1, "body": 1},
    )
    yt_comments_docs = await yt_comments_cursor.to_list(length=500)
    yt_sent_labels = [d.get("sentiment_label") for d in yt_comments_docs if d.get("sentiment_label")]

    # If MongoDB has insufficient YouTube comments for this video, fetch live from YouTube API.
    # YouTube API returns at most 100 per page; fetch up to 200 for a richer signal.
    if len(yt_sent_labels) < 20:
        live_yt_bodies = await _fetch_youtube_video_comments(vid_id, max_comments=200)
        if live_yt_bodies:
            try:
                svc = _get_sentiment_svc()
                batch_res = await _asyncio.to_thread(svc.analyze_batch, live_yt_bodies[:200])
                yt_sent_labels.extend([r.label.value for r in batch_res])
            except Exception:
                pass

    yt_sentiment: Optional[PlatformSentimentBreakdown] = None
    if yt_sent_labels:
        yt_sentiment = _compute_sentiment_breakdown(yt_sent_labels)

    # 6. Reddit sentiment
    rd_sentiment: Optional[PlatformSentimentBreakdown] = None
    if reddit_sentiments:
        rd_sentiment = _compute_sentiment_breakdown(reddit_sentiments)

    disparity_note: Optional[str] = None
    gap = _sentiment_gap(yt_sentiment, rd_sentiment)
    if _has_samples(yt_sentiment) and _has_samples(rd_sentiment):
        subs_text = f" across {len(subreddits_set)} subreddits" if subreddits_set else ""
        if gap > 0.15:
            disparity_note = (
                f"YouTube audience is significantly more positive (+{int(gap*100)}% gap; "
                f"{int(yt_sentiment.positive*100)}% positive on YouTube vs {int(rd_sentiment.positive*100)}% on Reddit{subs_text}). "
                "Reddit discussions reflect deeper critical debate and community skepticism."
            )
        elif gap < -0.15:
            disparity_note = (
                f"Reddit discussion is significantly more positive (+{int(abs(gap)*100)}% gap; "
                f"{int(rd_sentiment.positive*100)}% positive on Reddit vs {int(yt_sentiment.positive*100)}% on YouTube). "
                "The Reddit community responded notably more favorably than YouTube comment threads."
            )
        else:
            disparity_note = (
                f"Sentiment is well aligned between YouTube ({int(yt_sentiment.positive*100)}% pos) "
                f"and Reddit ({int(rd_sentiment.positive*100)}% pos{subs_text})."
            )
    elif yt_sentiment and yt_sentiment.sample_size > 0:
        disparity_note = (
            f"YouTube audience sentiment is {int(yt_sentiment.positive*100)}% positive "
            f"({yt_sentiment.sample_size} comments). "
            "No Reddit discussions were found that reference this specific video "
            "(checked by video URL, bare ID, and exact title). "
            "The metrics above reflect real data — 0 Reddit discussions, 0 subreddits."
        )
    elif rd_sentiment and rd_sentiment.sample_size > 0:
        disparity_note = f"Reddit discussion sentiment is {int(rd_sentiment.positive*100)}% positive ({rd_sentiment.sample_size} comments analyzed)."

    topics = _extract_topics_from_texts(discussion_bodies, top_n=6)

    return VideoCrossPlatformEngagementResponse(
        youtube_video_id=vid_id,
        youtube_url=canonical_yt_url,
        youtube_title=title or f"Video {vid_id}",
        youtube_channel_title=channel_title,
        youtube_thumbnail_url=thumbnail_url,
        youtube_views=views,
        youtube_likes=likes,
        youtube_comment_count=comment_count,
        youtube_published_at=yt_published_at,
        youtube_tags=yt_tags[:6],
        subreddits_count=len(subreddits_set),
        subreddits_list=sorted(list(subreddits_set)),
        total_reddit_discussions=len(reddit_discussions),
        reddit_posts_count=len(post_ids_set),
        reddit_total_upvotes=reddit_upvotes_total,
        reddit_total_comments=reddit_total_comments_sum,
        reddit_first_shared_at=first_shared_str,
        reddit_latest_shared_at=latest_shared_str,
        propagation_delay_hours=propagation_delay_hours,
        propagation_speed=propagation_speed,
        youtube_sentiment=yt_sentiment,
        reddit_sentiment=rd_sentiment,
        sentiment_disparity_note=disparity_note,
        discussions=top_discussions,
        topics=topics,
    )


@router.get(
    "/sentiment-comparison",
    response_model=CrossPlatformSentimentComparison,
    summary="Audience response sentiment comparison between YouTube and Reddit",
)
async def get_sentiment_comparison(
    subreddit_name: Optional[str] = Query(
        default=None,
        description="Subreddit name to compare against YouTube sentiment",
    ),
    video_url_or_id: Optional[str] = Query(
        default=None,
        description="Optional YouTube video URL or ID to analyze specific video sentiment",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> CrossPlatformSentimentComparison:
    """
    Computes aggregated audience sentiment distributions for YouTube vs Reddit
    using real NLP sentiment classification on actual comments.
    """
    from app.services.external.reddit_client import RedditClient
    from app.services.external.youtube_client import YouTubeClient

    comments_coll = get_comments_collection()
    svc = _get_sentiment_svc()

    # 1. Fetch Reddit sentiment distribution
    rd_filter: Dict[str, Any] = {"platform": "reddit"}
    clean_sub = None
    if subreddit_name:
        clean_sub = subreddit_name.strip().lstrip("/").replace("r/", "").replace("/r/", "").strip().lower()
        rd_filter["parent_id"] = {"$regex": f"^{re.escape(clean_sub)}$", "$options": "i"}

    vid_id = _extract_video_id(video_url_or_id) if video_url_or_id else None

    rd_labels: List[str] = []

    if vid_id:
        # Match Reddit comments from MongoDB
        rd_cursor = comments_coll.find(
            {"platform": "reddit", "body": {"$regex": re.escape(vid_id), "$options": "i"}},
            {"_id": 0, "sentiment_label": 1, "body": 1},
        ).limit(100)
        rd_docs = await rd_cursor.to_list(length=100)
        rd_labels = [d.get("sentiment_label") for d in rd_docs if d.get("sentiment_label")]
        unlabeled_rd = [d["body"] for d in rd_docs if not d.get("sentiment_label") and d.get("body")]

        if len(rd_labels) < 5 and unlabeled_rd:
            try:
                batch_res = await _asyncio.to_thread(svc.analyze_batch, unlabeled_rd[:40])
                rd_labels.extend([r.label.value for r in batch_res])
            except Exception:
                pass

        # If MongoDB has few Reddit comments, fetch live discussions
        if len(rd_labels) < 5:
            v_title = ""
            v_channel = ""
            v_tags: List[str] = []
            try:
                yt_cli = YouTubeClient()
                v_det = await _asyncio.to_thread(yt_cli._service.videos().list(part="snippet", id=vid_id).execute)
                v_items = v_det.get("items", [])
                if v_items:
                    snip = v_items[0].get("snippet", {})
                    v_title = snip.get("title", "")
                    v_channel = snip.get("channelTitle", "")
                    v_tags = snip.get("tags", [])
            except Exception:
                pass

            live_posts = await _fetch_reddit_video_discussions(
                vid_id=vid_id,
                title=v_title,
                channel_title=v_channel,
                tags=v_tags,
            )
            live_bodies = []
            for lp in live_posts:
                for c in lp.get("comments", []):
                    if c.get("body"):
                        live_bodies.append(c["body"])
                if lp.get("title"):
                    live_bodies.append(lp["title"])
            if live_bodies:
                try:
                    batch_res = await _asyncio.to_thread(svc.analyze_batch, live_bodies[:60])
                    rd_labels.extend([r.label.value for r in batch_res])
                except Exception:
                    pass

    elif clean_sub:
        rd_cursor = comments_coll.find(
            {"platform": "reddit", "parent_id": {"": f"^{re.escape(clean_sub)}$", "off on off off off off off off off off on off on off off off off off on off off off on on off off off off on off off off off off off off off off off off off on off off off off off off off on off on on off off off on off off on off off on off off on off on off off on off on off off off off on off off off on off off on off off off off off off off off on off on off off on off off off off off off off off off off off off on off off off on off on off on on off off off off on on off off on on off on off on on off off off off on on off off on off off off off off on off off on off off on off off off off off off on off off off off on on off on off off off off off on off on off off off off off off off off off off on on off on off off off": "i"}},
            {"_id": 0, "sentiment_label": 1, "body": 1},
        ).limit(200)
        rd_docs = await rd_cursor.to_list(length=200)
        rd_labels = [d.get("sentiment_label") for d in rd_docs if d.get("sentiment_label")]
        unlabeled_rd = [d["body"] for d in rd_docs if not d.get("sentiment_label") and d.get("body")]

        if len(rd_labels) < 5 and unlabeled_rd:
            try:
                batch_res = await _asyncio.to_thread(svc.analyze_batch, unlabeled_rd[:40])
                rd_labels.extend([r.label.value for r in batch_res])
            except Exception:
                pass

        if len(rd_labels) < 3:
            try:
                reddit_client = RedditClient()
                hot = await reddit_client.fetch_hot_threads(clean_sub, limit=3)
                live_bodies = []
                for t in hot.threads[:2]:
                    det = await reddit_client.fetch_post_details(t.post_id, comment_limit=10)
                    live_bodies.extend([c.body for c in det.comments if c.body])
                if live_bodies:
                    batch_res = await _asyncio.to_thread(svc.analyze_batch, live_bodies[:30])
                    rd_labels.extend([r.label.value for r in batch_res])
            except Exception:
                pass

    rd_sentiment = _compute_sentiment_breakdown(rd_labels)

    # 2. Fetch YouTube sentiment distribution
    yt_labels: List[str] = []
    if vid_id:
        yt_cursor = comments_coll.find(
            {"platform": "youtube", "": [{"video_id": vid_id}, {"parent_id": vid_id}]},
            {"_id": 0, "sentiment_label": 1, "body": 1},
        ).limit(200)
        yt_docs = await yt_cursor.to_list(length=200)
        yt_labels = [d.get("sentiment_label") for d in yt_docs if d.get("sentiment_label")]
        unlabeled_yt = [d["body"] for d in yt_docs if not d.get("sentiment_label") and d.get("body")]

        if len(yt_labels) < 5 and unlabeled_yt:
            try:
                batch_res = await _asyncio.to_thread(svc.analyze_batch, unlabeled_yt[:40])
                yt_labels.extend([r.label.value for r in batch_res])
            except Exception:
                pass

        # If MongoDB has few YouTube comments, fetch live from video directly
        if len(yt_labels) < 5:
            live_yt = await _fetch_youtube_video_comments(vid_id, max_comments=50)
            if live_yt:
                try:
                    batch_res = await _asyncio.to_thread(svc.analyze_batch, live_yt[:50])
                    yt_labels.extend([r.label.value for r in batch_res])
                except Exception:
                    pass

    elif clean_sub:
        yt_filter = {"platform": "youtube"}
        yt_cursor = comments_coll.find(yt_filter, {"_id": 0, "sentiment_label": 1, "body": 1}).limit(200)
        yt_docs = await yt_cursor.to_list(length=200)
        yt_labels = [d.get("sentiment_label") for d in yt_docs if d.get("sentiment_label")]
        unlabeled_yt = [d["body"] for d in yt_docs if not d.get("sentiment_label") and d.get("body")]

        if len(yt_labels) < 5 and unlabeled_yt:
            try:
                batch_res = await _asyncio.to_thread(svc.analyze_batch, unlabeled_yt[:40])
                yt_labels.extend([r.label.value for r in batch_res])
            except Exception:
                pass

        if len(yt_labels) < 3:
            try:
                yt_client = YouTubeClient()
                s_req = yt_client._service.search().list(part="snippet", q=clean_sub, type="video", maxResults=2)
                s_data = await _asyncio.to_thread(s_req.execute)
                live_yt_bodies = []
                for it in s_data.get("items", []):
                    v_id = it.get("id", {}).get("videoId")
                    if v_id:
                        c_req = yt_client._service.commentThreads().list(part="snippet", videoId=v_id, maxResults=15)
                        c_data = await _asyncio.to_thread(c_req.execute)
                        for item in c_data.get("items", []):
                            text = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textDisplay", "")
                            if text:
                                live_yt_bodies.append(text)
                if live_yt_bodies:
                    batch_res = await _asyncio.to_thread(svc.analyze_batch, live_yt_bodies[:30])
                    yt_labels.extend([r.label.value for r in batch_res])
            except Exception:
                pass

    yt_sentiment = _compute_sentiment_breakdown(yt_labels)

    # Single shared gap rule (0.0 unless both sides measured, 2-decimal rounding).
    gap = _sentiment_gap(yt_sentiment, rd_sentiment)

    if yt_sentiment.sample_size == 0 and rd_sentiment.sample_size == 0:
        summary = "No sentiment comments found for this query yet. Try scanning an active subreddit or video."
    elif yt_sentiment.sample_size == 0:
        summary = f"Reddit discussion sentiment is {int(rd_sentiment.positive*100)}% positive ({rd_sentiment.sample_size} comments analyzed)."
    elif rd_sentiment.sample_size == 0:
        summary = f"YouTube audience sentiment is {int(yt_sentiment.positive*100)}% positive ({yt_sentiment.sample_size} comments analyzed). No Reddit community discussions found for this video yet."
    elif gap > 0.10:
        summary = (
            f"YouTube reception is notably more positive ({int(yt_sentiment.positive*100)}%) "
            f"than Reddit community discussion ({int(rd_sentiment.positive*100)}%). "
            "Reddit discussions show deeper critical debate and contrarian perspectives."
        )
    elif gap < -0.10:
        summary = (
            f"Reddit discussion is more positive ({int(rd_sentiment.positive*100)}%) "
            f"than YouTube audience ({int(yt_sentiment.positive*100)}%)."
        )
    else:
        summary = f"Audience response is closely aligned between YouTube ({int(yt_sentiment.positive*100)}% pos) and Reddit ({int(rd_sentiment.positive*100)}% pos)."

    return CrossPlatformSentimentComparison(
        youtube_sentiment=yt_sentiment,
        reddit_sentiment=rd_sentiment,
        sentiment_gap=gap,
        audience_response_summary=summary,
    )


@router.get(
    "/topic-correlation",
    response_model=CrossPlatformTopicCorrelation,
    summary="Correlated discussion topics across YouTube and Reddit",
)
async def get_topic_correlation(
    subreddit_name: Optional[str] = Query(
        default=None,
        description="Subreddit name to correlate topics with YouTube",
    ),
) -> CrossPlatformTopicCorrelation:
    """
    Extracts top keywords and topics across YouTube video payloads and Reddit
    comments, discovering shared cross-platform themes.
    """
    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # Reddit comments texts
    rd_filter: Dict[str, Any] = {"platform": "reddit"}
    if subreddit_name:
        clean_sub = subreddit_name.strip().lstrip("/").replace("r/", "").replace("/r/", "").strip().lower()
        rd_filter["parent_id"] = {"$regex": f"^{re.escape(clean_sub)}$", "$options": "i"}

    rd_cursor = comments_coll.find(rd_filter, {"_id": 0, "body": 1}).limit(300)
    rd_docs = await rd_cursor.to_list(length=300)
    rd_texts = [d.get("body", "") for d in rd_docs]
    reddit_topics = _extract_topics_from_texts(rd_texts, top_n=12)

    # YouTube titles and tags
    yt_cursor = payloads_coll.find({"platform": "youtube"}, {"_id": 0, "title": 1, "raw": 1}).limit(100)
    yt_docs = await yt_cursor.to_list(length=100)
    yt_texts = [d.get("title", "") for d in yt_docs]
    youtube_topics = _extract_topics_from_texts(yt_texts, top_n=12)

    # Shared topics
    shared = [t for t in reddit_topics if t in youtube_topics]
    if not shared:
        shared = (reddit_topics[:3] + youtube_topics[:3])[:4]

    top_correlations = [
        {
            "topic": t,
            "youtube_relevance": "High" if t in youtube_topics else "Medium",
            "reddit_discussion_volume": "High" if t in reddit_topics else "Medium",
        }
        for t in list(dict.fromkeys(shared + reddit_topics[:4] + youtube_topics[:4]))[:8]
    ]

    return CrossPlatformTopicCorrelation(
        shared_topics=shared,
        youtube_topics=youtube_topics,
        reddit_topics=reddit_topics,
        top_correlations=top_correlations,
    )


@router.get(
    "/top-videos",
    response_model=List[SharedVideoItem],
    summary="Top YouTube videos for a given topic keyword",
)
async def get_top_videos_for_topic(
    topic: str = Query(
        ...,
        description="Topic / keyword to search for (e.g. 'gaming', 'python tutorial')",
    ),
    max_results: int = Query(
        default=10,
        ge=1,
        le=25,
        description="Number of top videos to return",
    ),
) -> List[SharedVideoItem]:
    """
    Uses YouTube Data API to search for the most viewed videos for a topic.
    Returns them in SharedVideoItem format.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError
    import asyncio as _asyncio

    try:
        yt_client = YouTubeClient()

        search_request = yt_client._service.search().list(
            part="snippet",
            q=topic,
            type="video",
            order="viewCount",
            maxResults=max_results,
            relevanceLanguage="en",
        )
        search_data = await _asyncio.to_thread(search_request.execute)
        video_ids = [
            item["id"]["videoId"]
            for item in search_data.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

        if not video_ids:
            return []

        stats_request = yt_client._service.videos().list(
            part="snippet,statistics",
            id=",".join(video_ids),
        )
        stats_data = await _asyncio.to_thread(stats_request.execute)

        results: List[SharedVideoItem] = []
        for item in stats_data.get("items", []):
            vid_id = item.get("id", "")
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            views = int(stats.get("viewCount", 0) or 0)
            likes = int(stats.get("likeCount", 0) or 0)

            # No measured comments exist for live-search results (they were
            # never ingested), so report an honest empty breakdown instead of
            # inferring sentiment from like ratios. Analyze the video above
            # for a real YouTube-vs-Reddit comparison.

            results.append(
                SharedVideoItem(
                    youtube_video_id=vid_id,
                    youtube_url=f"https://www.youtube.com/watch?v={vid_id}",
                    reddit_post_ids=[],
                    reddit_subreddits=[],
                    total_reddit_shares=0,
                    youtube_views=views,
                    youtube_likes=likes,
                    youtube_comment_count=int(stats.get("commentCount", 0) or 0),
                    youtube_title=snippet.get("title", ""),
                    youtube_thumbnail_url=thumb,
                    youtube_channel_title=snippet.get("channelTitle", ""),
                    youtube_published_at=snippet.get("publishedAt"),
                    youtube_tags=snippet.get("tags", [])[:5],
                    youtube_sentiment=_empty_breakdown(),
                    topics=snippet.get("tags", [])[:4],
                )
            )

        results.sort(key=lambda x: x.youtube_views or 0, reverse=True)
        return results

    except YouTubeAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YouTube API error: {exc}",
        )


@router.get(
    "/engagement-comparison",
    response_model=List[PlatformEngagementComparison],
    summary="Comparative normalised engagement index across both platforms",
)
async def get_engagement_comparison(
    session: AsyncSession = Depends(get_db_session),
) -> List[PlatformEngagementComparison]:
    """
    For every tracked account (YouTube channels + Reddit subreddits), compute
    a normalised engagement index (0–100).
    """
    payloads_coll = get_video_payloads_collection()

    stmt = select(PlatformAccount).order_by(
        PlatformAccount.platform, PlatformAccount.display_name
    )
    result = await session.execute(stmt)
    accounts = result.scalars().all()

    if not accounts:
        return []

    comparisons: List[PlatformEngagementComparison] = []

    for acc in accounts:
        platform_str = acc.platform.value
        payload_doc = await payloads_coll.find_one(
            {"platform": platform_str, "platform_id": acc.platform_id},
            {"_id": 0, "stats": 1},
        )
        stats = (payload_doc or {}).get("stats", {})

        norm_score = _normalise_engagement(stats, platform_str)

        comparisons.append(
            PlatformEngagementComparison(
                platform=platform_str,
                raw_engagement={
                    "account_id": acc.platform_id,
                    "display_name": acc.display_name,
                    **{k: v for k, v in stats.items() if isinstance(v, (int, float))},
                },
                normalised_score=norm_score,
            )
        )

    return comparisons


@router.get(
    "/correlation-summary",
    response_model=CrossPlatformCorrelationResponse,
    summary="Full cross-platform correlation in a single payload",
)
async def get_correlation_summary(
    subreddit_name: Optional[str] = Query(
        default=None,
        description="Subreddit to scan for YouTube links",
    ),
    video_url_or_id: Optional[str] = Query(
        default=None,
        description="Optional YouTube video URL or ID to focus correlation on",
    ),
    comment_scan_limit: int = Query(
        default=300,
        ge=50,
        le=2000,
        description="Reddit comments to scan for YouTube URLs",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> CrossPlatformCorrelationResponse:
    """
    Combines `shared-videos`, `engagement-comparison`, `sentiment-comparison`,
    and `topic-correlation` into a single response.
    """
    shared = await get_shared_videos(
        subreddit_name=subreddit_name,
        video_url_or_id=video_url_or_id,
        limit=comment_scan_limit,
    )
    comparison = await get_engagement_comparison(session=session)
    sent_comp = await get_sentiment_comparison(subreddit_name=subreddit_name, video_url_or_id=video_url_or_id, session=session)
    topic_corr = await get_topic_correlation(subreddit_name=subreddit_name)

    yt_scores = [c.normalised_score for c in comparison if c.platform == "youtube"]
    rd_scores = [c.normalised_score for c in comparison if c.platform == "reddit"]

    import statistics as _stats

    def _safe_mean(lst: List[float]) -> float:
        return round(_stats.mean(lst), 2) if lst else 0.0

    delays = [v.propagation_delay_hours for v in shared if v.propagation_delay_hours is not None]
    avg_propagation_lag = _safe_mean(delays) if delays else 0.0

    correlation_summary: Dict[str, Any] = {
        "total_tracked_youtube_channels": len(yt_scores),
        "total_tracked_subreddits": len(rd_scores),
        "avg_youtube_engagement_score": _safe_mean(yt_scores),
        "avg_reddit_engagement_score": _safe_mean(rd_scores),
        "total_cross_platform_videos": len(shared),
        "avg_propagation_lag_hours": avg_propagation_lag,
        "sentiment_gap": sent_comp.sentiment_gap,
        "top_shared_video_id": shared[0].youtube_video_id if shared else None,
        "top_shared_video_title": shared[0].youtube_title if shared else None,
        "top_shared_video_reddit_shares": shared[0].total_reddit_shares if shared else 0,
        "total_discussions_linked": sum(len(v.reddit_discussions) for v in shared),
        "note": (
            "Cross-Platform Mode links YouTube videos with Reddit posts and discussions. "
            "Combines engagement metrics, timestamps, sentiment, topics, and discussion activity."
        ),
    }

    return CrossPlatformCorrelationResponse(
        shared_videos=shared,
        platform_comparison=comparison,
        sentiment_comparison=sent_comp,
        topic_correlation=topic_corr,
        correlation_summary=correlation_summary,
    )
