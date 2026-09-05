"""
Analytics services — sentiment analysis and engagement prediction.
"""

from app.services.analytics.sentiment_service import (
    SentimentService,
    SentimentLabel,
    SentimentResult,
)
from app.services.analytics.prediction_engine import (
    PredictionEngine,
    FeaturePipeline,
    ForecastResult,
)
from app.services.analytics.category_benchmarks import (
    CategoryBenchmark,
    CATEGORY_BENCHMARKS,
    detect_category,
    generate_category_forecast,
    generate_warmup_records,
)
from app.services.analytics.semantic_matcher import (
    SemanticMatcher,
    get_semantic_matcher,
)

__all__ = [
    "SentimentService",
    "SentimentLabel",
    "SentimentResult",
    "PredictionEngine",
    "FeaturePipeline",
    "ForecastResult",
    "CategoryBenchmark",
    "CATEGORY_BENCHMARKS",
    "detect_category",
    "generate_category_forecast",
    "generate_warmup_records",
    "SemanticMatcher",
    "get_semantic_matcher",
]
