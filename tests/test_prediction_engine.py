"""
Tests for Engagement Prediction Engine & Global Category Benchmarks / Transfer Learning
======================================================================================
Verifies:
1. Category benchmark definitions, aliases, and detection heuristics.
2. Cold-start forecasting ($N = 0$) using category priors.
3. Warmup synthesis and Bayesian shrinkage / transfer learning ($1 <= N < 5$).
4. Standard forecasting ($N >= 5$) with channel history.
5. Scale normalization to prevent small channels from being artificially inflated.
6. FeaturePipeline lag generation with short and warmup-augmented histories.
"""

from datetime import datetime, timedelta, timezone
import pytest
import numpy as np
import pandas as pd

from app.services.analytics.category_benchmarks import (
    CATEGORY_BENCHMARKS,
    CategoryBenchmark,
    detect_category,
    generate_category_forecast,
    generate_warmup_records,
)
from app.services.analytics.prediction_engine import (
    PredictionEngine,
    FeaturePipeline,
    ForecastResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_post_factory():
    """Factory to generate realistic historical post dictionaries."""
    def _create(count: int, base_views: float = 1000.0, category: str = "tech"):
        records = []
        start_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(count):
            dt = start_time + timedelta(days=i * 2)
            views = base_views * (1.0 + 0.05 * i)
            records.append({
                "published_at": dt.isoformat(),
                "title": f"Post #{i + 1} about software development and python code",
                "engagement_metrics": {
                    "views": round(views, 1),
                    "likes": round(views * 0.06, 1),
                    "comments": round(views * 0.01, 1),
                    "shares": round(views * 0.005, 1),
                    "saves": round(views * 0.002, 1),
                },
                "sentiment": {
                    "positive": 0.65,
                    "neutral": 0.25,
                    "negative": 0.10,
                },
                "topic_encoded": 0,
                "category": category,
            })
        return records
    return _create


# ── 1. Benchmark Registry & Metadata ──────────────────────────────────────────

def test_category_benchmarks_registry():
    """Verify all 7 standard categories exist and have valid empirical parameters."""
    expected_categories = {"gaming", "tech", "entertainment", "education", "news", "music", "general"}
    assert expected_categories.issubset(set(CATEGORY_BENCHMARKS.keys()))

    for cat_name, bench in CATEGORY_BENCHMARKS.items():
        assert isinstance(bench, CategoryBenchmark)
        assert bench.base_views > 0
        assert bench.views_std > 0
        assert 0.0 < bench.likes_per_view < 1.0
        assert 0.0 < bench.comments_per_view < 1.0
        assert -0.5 < bench.growth_rate_per_post < 0.5
        assert "positive" in bench.sentiment_prior
        assert "neutral" in bench.sentiment_prior
        assert "negative" in bench.sentiment_prior
        
        bench_dict = bench.to_dict()
        assert bench_dict["name"] == cat_name
        assert bench_dict["base_views"] == bench.base_views


# ── 2. Category Detection ─────────────────────────────────────────────────────

def test_detect_category_explicit():
    """Direct explicit category matches and alias normalization."""
    assert detect_category(explicit_category="tech") == "tech"
    assert detect_category(explicit_category="TECHNOLOGY") == "tech"
    assert detect_category(explicit_category="software") == "tech"
    assert detect_category(explicit_category="gaming") == "gaming"
    assert detect_category(explicit_category="videogames") == "gaming"
    assert detect_category(explicit_category="esports") == "gaming"
    assert detect_category(explicit_category="movies") == "entertainment"
    assert detect_category(explicit_category="science") == "education"
    assert detect_category(explicit_category="political") == "news"
    assert detect_category(explicit_category="songs") == "music"


def test_detect_category_channel_metadata():
    """Detect category from channel metadata topic/category or keyword fields."""
    # Direct field
    assert detect_category(channel_metadata={"category": "gaming"}) == "gaming"
    assert detect_category(channel_metadata={"subreddit": "technology"}) == "tech"
    
    # Keyword inference from channel description
    meta = {
        "title": "CodeCraft",
        "description": "Daily python tutorials, coding exercises, and AI software reviews",
    }
    assert detect_category(channel_metadata=meta) == "tech"

    # Entertainment keywords
    meta_ent = {
        "title": "MovieBuffs",
        "description": "Official trailers, hollywood celebrity gossip, film analysis and comedy memes",
    }
    assert detect_category(channel_metadata=meta_ent) == "entertainment"


def test_detect_category_history_records():
    """Detect category from recent post titles/content."""
    records = [
        {"title": "Minecraft 1.21 Speedrun Walkthrough - Nether Fortress Strategy"},
        {"title": "Top 10 RPG Twitch games on Steam this week"},
    ]
    assert detect_category(history_records=records) == "gaming"


def test_detect_category_fallback():
    """Unknown or empty inputs default safely to 'general'."""
    assert detect_category() == "general"
    assert detect_category(channel_metadata={"title": "My personal vlog and random thoughts"}) == "general"
    assert detect_category(explicit_category="totally_unknown_niche") == "general"


# ── 3. Warmup Synthesis ───────────────────────────────────────────────────────

def test_generate_warmup_records():
    """Verify synthetic warmup records prepend cleanly with appropriate timestamps and scales."""
    base_time = datetime(2026, 8, 10, 10, 0, 0, tzinfo=timezone.utc)
    base_record = {
        "published_at": base_time.isoformat(),
        "engagement_metrics": {"views": 500, "likes": 30, "comments": 5},
    }

    warmup = generate_warmup_records(
        category="tech",
        needed_count=3,
        base_record=base_record,
        observed_views=500.0,
    )

    assert len(warmup) == 3
    # Ordered oldest -> newest, all before base_time
    dt_prev = None
    for rec in warmup:
        dt = datetime.fromisoformat(rec["published_at"])
        assert dt < base_time
        if dt_prev is not None:
            assert dt > dt_prev  # Chronological order
        dt_prev = dt

        assert rec["is_warmup_prior"] is True
        assert rec["category"] == "tech"
        # Scale should be close to 500, not 6200 (global tech benchmark)
        views = rec["engagement_metrics"]["views"]
        assert 350.0 <= views <= 550.0
        assert rec["engagement_metrics"]["likes"] > 0
        assert rec["engagement_metrics"]["comments"] > 0


def test_generate_warmup_records_empty():
    assert generate_warmup_records("gaming", needed_count=0) == []
    assert generate_warmup_records("gaming", needed_count=-2) == []


# ── 4. Cold-Start Regime (N = 0) ──────────────────────────────────────────────

def test_cold_start_category_benchmark_forecast():
    """
    When history is empty (N = 0), engine returns category benchmark forecast
    with engine='category_benchmark' and prior_weight=1.0.
    """
    engine = PredictionEngine()
    forecasts = engine.forecast_next_posts([], num_posts=5, category="gaming")

    assert len(forecasts) == 5
    for i, step in enumerate(forecasts, start=1):
        assert step["forecast_step"] == i
        assert step["engine"] == "category_benchmark"
        assert step["category"] == "gaming"
        assert step["prior_weight"] == 1.0
        assert step["predicted_views"] > 0
        assert step["predicted_likes"] > 0
        assert step["predicted_comments"] > 0
        ci_low, ci_high = step["confidence_interval"]
        assert ci_low < step["predicted_views"] < ci_high


def test_cold_start_forecast_step_growth():
    """Verify post-over-post growth trend is reflected in benchmark forecast."""
    engine = PredictionEngine()
    forecasts = engine.forecast_next_posts([], num_posts=3, category="music")
    # Music has +3.5% growth rate per post
    assert forecasts[1]["predicted_views"] > forecasts[0]["predicted_views"]
    assert forecasts[2]["predicted_views"] > forecasts[1]["predicted_views"]


# ── 5. Few Data Points & Transfer Learning (1 <= N < 5) ────────────────────────

def test_few_data_points_transfer_learning(sample_post_factory):
    """
    When channel has 1-4 posts, engine uses warmup synthesis and empirical Bayes
    shrinkage, tagging engine='transfer_learning' and prior_weight=(1 - N/5).
    """
    engine = PredictionEngine()
    # 2 historical posts with observed scale ~300 views
    history = sample_post_factory(count=2, base_views=300.0, category="tech")
    
    forecasts = engine.forecast_next_posts(history, num_posts=5, category="tech")

    assert len(forecasts) == 5
    expected_prior_weight = round(1.0 - (2 / 5.0), 4)  # 0.60

    for i, step in enumerate(forecasts, start=1):
        assert step["forecast_step"] == i
        assert step["engine"] == "transfer_learning"
        assert step["category"] == "tech"
        assert round(step["prior_weight"], 2) == expected_prior_weight
        # Crucial check: Scale should be blended around ~300 views, NOT blown up to tech benchmark 6200
        assert 200.0 <= step["predicted_views"] <= 500.0
        ci_low, ci_high = step["confidence_interval"]
        assert ci_low < step["predicted_views"] < ci_high


def test_single_data_point_transfer_learning(sample_post_factory):
    """When channel has exactly 1 post (N = 1), prior_weight = 0.8."""
    engine = PredictionEngine()
    history = sample_post_factory(count=1, base_views=150.0, category="education")

    forecasts = engine.forecast_next_posts(history, num_posts=3, category="education")
    assert len(forecasts) == 3
    for step in forecasts:
        assert step["engine"] == "transfer_learning"
        assert round(step["prior_weight"], 2) == 0.80
        # Remains in the right order of magnitude
        assert 100.0 <= step["predicted_views"] <= 250.0


def test_four_data_points_transfer_learning(sample_post_factory):
    """When channel has 4 posts (N = 4), prior_weight = 0.2 (mostly channel data)."""
    engine = PredictionEngine()
    history = sample_post_factory(count=4, base_views=10000.0, category="entertainment")

    forecasts = engine.forecast_next_posts(history, num_posts=3, category="entertainment")
    assert len(forecasts) == 3
    for step in forecasts:
        assert step["engine"] == "transfer_learning"
        assert round(step["prior_weight"], 2) == 0.20
        assert step["predicted_views"] >= 9000.0


# ── 6. Sufficient History Regime (N >= 5) ──────────────────────────────────────

def test_sufficient_history_forecast(sample_post_factory):
    """
    When channel has >= 5 posts, model runs channel inference directly
    with prior_weight=0.0.
    """
    engine = PredictionEngine()
    history = sample_post_factory(count=8, base_views=2000.0, category="gaming")

    forecasts = engine.forecast_next_posts(history, num_posts=5, category="gaming")
    assert len(forecasts) == 5
    for i, step in enumerate(forecasts, start=1):
        assert step["forecast_step"] == i
        # Either xgboost or baseline_moving_avg depending on env
        assert step["engine"] in ("xgboost", "baseline_moving_avg")
        assert step["category"] == "gaming"
        assert step["prior_weight"] == 0.0
        assert step["predicted_views"] > 0


# ── 7. FeaturePipeline & Lag Generation ────────────────────────────────────────

def test_feature_pipeline_with_warmup(sample_post_factory):
    """
    Verify FeaturePipeline can fit and transform short history once augmented
    with warmup records without dropping all rows.
    """
    raw_history = sample_post_factory(count=2, base_views=400.0, category="tech")
    warmup = generate_warmup_records("tech", needed_count=3, base_record=raw_history[0], observed_views=400.0)
    augmented = warmup + raw_history
    assert len(augmented) == 5

    pipeline = FeaturePipeline(lag_steps=5)
    df = pipeline.fit_transform(augmented)

    assert not df.empty
    # Check that lag columns are present
    for lag in range(1, 6):
        assert f"views_lag{lag}" in df.columns
    assert "views_roll3_mean" in df.columns
    assert "views_roll3_std" in df.columns


# ── 8. Utility Methods ────────────────────────────────────────────────────────

def test_prediction_engine_benchmark_helpers():
    """Test get_category_benchmark and list_supported_categories."""
    engine = PredictionEngine()
    
    categories = engine.list_supported_categories()
    assert "tech" in categories
    assert "gaming" in categories
    assert "general" in categories

    tech_bench = engine.get_category_benchmark("technology")
    assert tech_bench["name"] == "tech"
    assert tech_bench["base_views"] == 6200.0
    assert tech_bench["likes_per_view"] == 0.055
