"""
Global Category Benchmarks & Transfer Learning Priors
====================================================
Provides empirical category priors and benchmarks (gaming, tech, entertainment,
education, news, music, general) for engagement forecasting.

When newly tracked social media channels have insufficient history (< 5 posts),
this module enables transfer learning by:
1. Detecting or accepting domain categories (e.g. "tech", "gaming").
2. Providing domain-calibrated priors for base engagement, like/comment ratios,
   and growth momentum.
3. Synthesizing scaled warmup history records so feature pipelines can compute
   lag and rolling window statistics without dropping data.
4. Supplying prior distributions for Bayesian shrinkage / empirical Bayes blending.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CategoryBenchmark:
    """Empirical prior benchmarks for a specific content category."""

    name: str
    display_name: str
    base_views: float
    views_std: float
    likes_per_view: float
    comments_per_view: float
    shares_per_view: float
    growth_rate_per_post: float          # Expected post-over-post growth trend (e.g. 0.02 = +2%)
    sentiment_prior: Dict[str, float]    # Positive, neutral, negative distribution
    weekend_multiplier: float = 1.0     # Temporal multiplier for weekend posts
    weekday_multiplier: float = 1.0     # Temporal multiplier for weekday posts
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "base_views": self.base_views,
            "views_std": self.views_std,
            "likes_per_view": self.likes_per_view,
            "comments_per_view": self.comments_per_view,
            "shares_per_view": self.shares_per_view,
            "growth_rate_per_post": self.growth_rate_per_post,
            "sentiment_prior": self.sentiment_prior,
            "weekend_multiplier": self.weekend_multiplier,
            "weekday_multiplier": self.weekday_multiplier,
            "keywords": self.keywords,
        }


# ── Curated Domain Priors ───────────────────────────────────────────────────

CATEGORY_BENCHMARKS: Dict[str, CategoryBenchmark] = {
    "gaming": CategoryBenchmark(
        name="gaming",
        display_name="Gaming & Esports",
        base_views=8500.0,
        views_std=3200.0,
        likes_per_view=0.075,
        comments_per_view=0.012,
        shares_per_view=0.005,
        growth_rate_per_post=0.025,
        sentiment_prior={"positive": 0.62, "neutral": 0.26, "negative": 0.12},
        weekend_multiplier=1.20,
        weekday_multiplier=0.92,
        keywords=[
            "game", "gaming", "playstation", "xbox", "nintendo", "steam", "gta",
            "minecraft", "fortnite", "fps", "rpg", "esports", "twitch", "gameplay",
            "walkthrough", "speedrun", "mod", "valve", "roblox",
        ],
    ),
    "tech": CategoryBenchmark(
        name="tech",
        display_name="Technology & Software",
        base_views=6200.0,
        views_std=2100.0,
        likes_per_view=0.055,
        comments_per_view=0.009,
        shares_per_view=0.008,
        growth_rate_per_post=0.020,
        sentiment_prior={"positive": 0.68, "neutral": 0.24, "negative": 0.08},
        weekend_multiplier=0.88,
        weekday_multiplier=1.05,
        keywords=[
            "tech", "technology", "software", "hardware", "python", "javascript",
            "ai", "coding", "developer", "computer", "linux", "apple", "google",
            "gadget", "review", "cybersecurity", "cloud", "code", "programming",
        ],
    ),
    "entertainment": CategoryBenchmark(
        name="entertainment",
        display_name="Entertainment & Pop Culture",
        base_views=14000.0,
        views_std=5500.0,
        likes_per_view=0.085,
        comments_per_view=0.015,
        shares_per_view=0.012,
        growth_rate_per_post=0.030,
        sentiment_prior={"positive": 0.58, "neutral": 0.28, "negative": 0.14},
        weekend_multiplier=1.15,
        weekday_multiplier=0.95,
        keywords=[
            "movie", "film", "cinema", "trailer", "tv", "celebrity", "show",
            "hollywood", "netflix", "drama", "comedy", "funny", "meme", "anime",
            "entertainment", "popculture", "series", "actor",
        ],
    ),
    "education": CategoryBenchmark(
        name="education",
        display_name="Education & Science",
        base_views=4800.0,
        views_std=1600.0,
        likes_per_view=0.065,
        comments_per_view=0.007,
        shares_per_view=0.010,
        growth_rate_per_post=0.015,
        sentiment_prior={"positive": 0.75, "neutral": 0.20, "negative": 0.05},
        weekend_multiplier=0.90,
        weekday_multiplier=1.04,
        keywords=[
            "education", "tutorial", "learn", "how to", "guide", "science",
            "math", "history", "physics", "lesson", "lecture", "university",
            "academy", "course", "study", "research", "explained",
        ],
    ),
    "news": CategoryBenchmark(
        name="news",
        display_name="News & Politics",
        base_views=9500.0,
        views_std=4000.0,
        likes_per_view=0.040,
        comments_per_view=0.025,
        shares_per_view=0.015,
        growth_rate_per_post=0.018,
        sentiment_prior={"positive": 0.42, "neutral": 0.33, "negative": 0.25},
        weekend_multiplier=0.85,
        weekday_multiplier=1.06,
        keywords=[
            "news", "politics", "breaking", "world", "economy", "election",
            "government", "report", "journalism", "press", "crisis",
            "parliament", "congress", "senate", "investigation", "headline",
        ],
    ),
    "music": CategoryBenchmark(
        name="music",
        display_name="Music & Audio",
        base_views=18000.0,
        views_std=7000.0,
        likes_per_view=0.090,
        comments_per_view=0.014,
        shares_per_view=0.015,
        growth_rate_per_post=0.035,
        sentiment_prior={"positive": 0.72, "neutral": 0.22, "negative": 0.06},
        weekend_multiplier=1.12,
        weekday_multiplier=0.95,
        keywords=[
            "music", "song", "album", "artist", "band", "track", "remix",
            "cover", "lyrics", "official audio", "official video", "soundtrack",
            "instrumental", "acoustic", "concert", "beat", "rap", "hip hop",
        ],
    ),
    "general": CategoryBenchmark(
        name="general",
        display_name="General Content",
        base_views=5000.0,
        views_std=2000.0,
        likes_per_view=0.060,
        comments_per_view=0.008,
        shares_per_view=0.005,
        growth_rate_per_post=0.020,
        sentiment_prior={"positive": 0.60, "neutral": 0.30, "negative": 0.10},
        weekend_multiplier=1.00,
        weekday_multiplier=1.00,
        keywords=[],
    ),
}

# Alias mappings for flexible category detection
_CATEGORY_ALIASES: Dict[str, str] = {
    "technology": "tech",
    "software": "tech",
    "coding": "tech",
    "games": "gaming",
    "videogames": "gaming",
    "esports": "gaming",
    "movies": "entertainment",
    "film": "entertainment",
    "popculture": "entertainment",
    "academic": "education",
    "science": "education",
    "tutorials": "education",
    "political": "news",
    "audio": "music",
    "songs": "music",
    "vlog": "general",
    "lifestyle": "general",
    "other": "general",
}


def detect_category(
    channel_metadata: Optional[Dict[str, Any]] = None,
    history_records: Optional[List[Dict[str, Any]]] = None,
    explicit_category: Optional[str] = None,
) -> str:
    """
    Detect or normalize the category of a channel / post collection.

    Parameters
    ----------
    channel_metadata : Optional[Dict]
        Metadata dict (can contain 'category', 'topic', 'title', 'description').
    history_records : Optional[List[Dict]]
        Recent post history records.
    explicit_category : Optional[str]
        Direct user or caller override.

    Returns
    -------
    str : Canonical category key in CATEGORY_BENCHMARKS (e.g. "tech", "gaming").
    """
    if explicit_category:
        clean = explicit_category.strip().lower()
        if clean in CATEGORY_BENCHMARKS:
            return clean
        if clean in _CATEGORY_ALIASES:
            return _CATEGORY_ALIASES[clean]

    # Inspect channel metadata if provided
    text_corpus: List[str] = []
    if channel_metadata:
        cat = channel_metadata.get("category") or channel_metadata.get("topic") or channel_metadata.get("subreddit")
        if cat:
            cat_clean = str(cat).strip().lower()
            if cat_clean in CATEGORY_BENCHMARKS:
                return cat_clean
            if cat_clean in _CATEGORY_ALIASES:
                return _CATEGORY_ALIASES[cat_clean]

        for k in ["title", "description", "display_name"]:
            val = channel_metadata.get(k)
            if isinstance(val, str):
                text_corpus.append(val.lower())

    # Inspect history records
    if history_records:
        for rec in history_records[:10]:
            cat = rec.get("category") or rec.get("topic") or rec.get("subreddit")
            if cat:
                cat_clean = str(cat).strip().lower()
                if cat_clean in CATEGORY_BENCHMARKS:
                    return cat_clean
                if cat_clean in _CATEGORY_ALIASES:
                    return _CATEGORY_ALIASES[cat_clean]

            for k in ["title", "description", "body", "text"]:
                val = rec.get(k)
                if isinstance(val, str):
                    text_corpus.append(val.lower())

    # Keyword frequency scoring across text corpus
    if text_corpus:
        combined_text = " ".join(text_corpus)
        category_scores: Dict[str, int] = {}
        for cat_name, bench in CATEGORY_BENCHMARKS.items():
            if cat_name == "general":
                continue
            score = sum(len(re.findall(r"\b" + re.escape(kw) + r"\b", combined_text)) for kw in bench.keywords)
            if score > 0:
                category_scores[cat_name] = score

        if category_scores:
            best_cat = max(category_scores.items(), key=lambda x: x[1])[0]
            return best_cat

    return "general"


def generate_category_forecast(
    category: str,
    num_posts: int = 5,
    scale_views: Optional[float] = None,
    scale_ratios: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Generate a pure category benchmark forecast.

    Parameters
    ----------
    category : str
        Category name (e.g. "tech", "gaming").
    num_posts : int
        Number of steps to forecast.
    scale_views : Optional[float]
        If the channel has an observed scale (e.g. 500 views), scale the forecast
        around this observed magnitude instead of global absolute medians.
    scale_ratios : Optional[Dict]
        Custom likes/comments ratios if partially known.

    Returns
    -------
    List[Dict] : List of ForecastResult-compatible dicts.
    """
    canon = detect_category(explicit_category=category)
    bench = CATEGORY_BENCHMARKS.get(canon, CATEGORY_BENCHMARKS["general"])

    base_v = float(scale_views) if (scale_views is not None and scale_views > 0) else bench.base_views
    l_ratio = (scale_ratios.get("likes_per_view") if scale_ratios else None) or bench.likes_per_view
    c_ratio = (scale_ratios.get("comments_per_view") if scale_ratios else None) or bench.comments_per_view

    results: List[Dict[str, Any]] = []
    current_views = base_v

    for step in range(1, num_posts + 1):
        # Compound growth trend
        current_views = current_views * (1.0 + bench.growth_rate_per_post)
        pv = max(0.0, current_views)
        pl = max(0.0, pv * l_ratio)
        pc = max(0.0, pv * c_ratio)

        # Domain-calibrated confidence intervals
        # If scaled to channel, relative spread reflects category std/mean
        rel_std = min(0.35, max(0.15, bench.views_std / bench.base_views))
        ci_low = max(0.0, pv * (1.0 - rel_std))
        ci_high = pv * (1.0 + rel_std)

        results.append({
            "forecast_step": step,
            "predicted_views": round(pv, 1),
            "predicted_likes": round(pl, 1),
            "predicted_comments": round(pc, 1),
            "confidence_interval": [round(ci_low, 1), round(ci_high, 1)],
            "engine": "category_benchmark",
            "category": canon,
            "prior_weight": 1.0,
        })

    return results


def generate_warmup_records(
    category: str,
    needed_count: int,
    base_record: Optional[Dict[str, Any]] = None,
    observed_views: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Synthesize preceding warmup historical records using the category prior.

    These records are prepended to sparse historical data (< 5 posts) so
    the FeaturePipeline can compute all lag and rolling window features
    without dropping real data points.

    Parameters
    ----------
    category : str
        Content category.
    needed_count : int
        How many synthetic warmup records to generate (e.g., 5 - len(history)).
    base_record : Optional[Dict]
        The earliest known real record, used for timestamp anchoring.
    observed_views : Optional[float]
        Mean observed views of the real records, for scaling.

    Returns
    -------
    List[Dict] : Synthetic historical records ordered oldest -> newest.
    """
    if needed_count <= 0:
        return []

    canon = detect_category(explicit_category=category)
    bench = CATEGORY_BENCHMARKS.get(canon, CATEGORY_BENCHMARKS["general"])

    # Anchor timestamp before earliest real record
    if base_record and base_record.get("published_at"):
        try:
            pub = base_record["published_at"]
            if isinstance(pub, str):
                anchor_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            else:
                anchor_dt = pub
        except Exception:
            anchor_dt = datetime.now(timezone.utc)
    else:
        anchor_dt = datetime.now(timezone.utc)

    scale_v = float(observed_views) if (observed_views is not None and observed_views > 0) else bench.base_views
    l_ratio = bench.likes_per_view
    c_ratio = bench.comments_per_view

    warmup_records: List[Dict[str, Any]] = []

    # Generate in reverse (from closest before real record backwards)
    for i in range(needed_count, 0, -1):
        dt = anchor_dt - timedelta(days=i * 3)
        # Slight dampening for earlier posts according to category growth rate
        v_scaled = scale_v / ((1.0 + bench.growth_rate_per_post) ** i)
        v = max(1.0, v_scaled)
        l = v * l_ratio
        c = v * c_ratio

        warmup_records.append({
            "published_at": dt.isoformat(),
            "engagement_metrics": {
                "views": round(v, 1),
                "likes": round(l, 1),
                "comments": round(c, 1),
                "shares": round(v * bench.shares_per_view, 1),
                "saves": 0.0,
            },
            "sentiment": dict(bench.sentiment_prior),
            "topic_encoded": 0,
            "is_warmup_prior": True,
            "category": canon,
        })

    return warmup_records
