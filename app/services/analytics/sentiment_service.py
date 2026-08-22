"""
Sentiment Analysis Service
==========================
Primary: HuggingFace pipeline using cardiffnlp/twitter-roberta-base-sentiment-latest
Fallback: NLTK VADER (activated automatically when the transformer model cannot be
          loaded or when inference throws an unexpected error).

Usage
-----
    from app.services.analytics.sentiment_service import SentimentService

    svc = SentimentService()

    # Single text
    result = svc.analyze("This video is absolutely amazing!")
    print(result.to_dict())
    # {'label': 'positive', 'score': 0.97, 'details': {...}}

    # Batch texts (e.g., a list of MongoDB comment bodies)
    results = svc.analyze_batch(["Great!", "Meh.", "Terrible."])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# cardiffnlp model has a 512-token limit; ~1 500 chars ≈ safe upper bound.
_MAX_CHARS = 1_500

# Label aliases the model may emit → our canonical three-way scheme.
_LABEL_MAP: Dict[str, str] = {
    # cardiffnlp labels
    "label_0": "negative",
    "label_1": "neutral",
    "label_2": "positive",
    # textual variants (other HF models)
    "negative": "negative",
    "neutral": "neutral",
    "positive": "positive",
    "neg": "negative",
    "neu": "neutral",
    "pos": "positive",
    # numeric shortcuts
    "0": "negative",
    "1": "neutral",
    "2": "positive",
}


# ── Data structures ──────────────────────────────────────────────────────────

class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass
class SentimentResult:
    """Structured output for a single text analysis."""

    label: SentimentLabel
    score: float  # confidence of the dominant label (0–1)
    details: Dict[str, float] = field(default_factory=dict)
    engine: str = "unknown"  # "transformer" | "vader"

    def to_dict(self) -> Dict:
        return {
            "label": self.label.value,
            "score": round(self.score, 4),
            "details": {k: round(v, 4) for k, v in self.details.items()},
            "engine": self.engine,
        }


# ── Service ──────────────────────────────────────────────────────────────────

class SentimentService:
    """
    Thread-safe sentiment analysis service.

    The constructor eagerly loads both backends.  If the transformer model
    cannot be fetched (no network, disk space, etc.) only VADER is available.
    If VADER is also unavailable all analyses return a neutral result with
    score 0.0 so the calling pipeline never crashes.
    """

    DEFAULT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._pipeline = None          # HuggingFace pipeline object
        self._vader = None             # NLTK SentimentIntensityAnalyzer
        self._active_engine: str = "none"

        self._load_transformer()
        self._load_vader()

    # ── Initialisation helpers ────────────────────────────────────────────

    def _load_transformer(self) -> None:
        """Try to load the HuggingFace sentiment pipeline."""
        try:
            import os
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
            os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

            from transformers import pipeline as hf_pipeline

            logger.info("Loading transformer model '%s' on CPU …", self.model_name)
            self._pipeline = hf_pipeline(
                "sentiment-analysis",
                model=self.model_name,
                top_k=None,           # return scores for ALL labels
                truncation=True,
                max_length=512,
                device="cpu",         # CPU prevents macOS Metal/MPS segmentation faults
            )
            self._active_engine = "transformer"
            logger.info("Transformer model loaded successfully on CPU.")
        except Exception as exc:
            logger.warning(
                "Could not load transformer model '%s': %s. "
                "Will fall back to VADER.",
                self.model_name,
                exc,
            )

    def _load_vader(self) -> None:
        """Ensure the VADER lexicon is available and instantiate the analyser."""
        try:
            import ssl
            import nltk
            from nltk.sentiment.vader import SentimentIntensityAnalyzer

            # Download lexicon only if not already present.
            try:
                nltk.data.find("sentiment/vader_lexicon.zip")
            except LookupError:
                logger.info("Downloading VADER lexicon …")
                downloaded = nltk.download("vader_lexicon", quiet=True)

                # macOS Python ships without root certificates which causes SSL
                # errors during the download.  Retry with verification disabled.
                if not downloaded:
                    logger.warning(
                        "Standard VADER download failed (likely SSL). "
                        "Retrying with SSL verification disabled …"
                    )
                    try:
                        _orig_ctx = ssl._create_default_https_context
                        ssl._create_default_https_context = ssl._create_unverified_context
                        nltk.download("vader_lexicon", quiet=True)
                    finally:
                        ssl._create_default_https_context = _orig_ctx  # always restore

            self._vader = SentimentIntensityAnalyzer()
            if self._active_engine == "none":
                self._active_engine = "vader"
            logger.info("VADER fallback initialised.")
        except Exception as exc:
            logger.error("Failed to initialise VADER: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """True if at least one backend is available."""
        return self._pipeline is not None or self._vader is not None

    def analyze(self, text: str) -> SentimentResult:
        """
        Analyse a single text string.

        Parameters
        ----------
        text:
            Raw text to classify (e.g., a YouTube comment body from MongoDB).

        Returns
        -------
        SentimentResult
            Always returns a result; falls back to neutral/0.0 if all engines
            are unavailable.
        """
        if not text or not text.strip():
            return SentimentResult(
                label=SentimentLabel.NEUTRAL,
                score=0.0,
                details={},
                engine="none",
            )

        safe_text = text[:_MAX_CHARS]

        # Prefer transformer; silently fall back to VADER on errors.
        if self._pipeline is not None:
            try:
                return self._run_transformer(safe_text)
            except Exception as exc:
                logger.warning("Transformer inference failed: %s. Using VADER.", exc)

        if self._vader is not None:
            return self._run_vader(safe_text)

        logger.error("No sentiment engine available — returning neutral.")
        return SentimentResult(
            label=SentimentLabel.NEUTRAL,
            score=0.0,
            details={},
            engine="none",
        )

    def analyze_batch(self, texts: List[str]) -> List[SentimentResult]:
        """
        Analyse a list of texts efficiently.

        When the transformer pipeline is available the batch is submitted in
        one forward pass (GPU-friendly).  VADER processes items sequentially
        as it has no native batching.

        Parameters
        ----------
        texts:
            List of raw text strings, e.g., all comment bodies for a video.

        Returns
        -------
        List[SentimentResult]
            Same length and order as *texts*.
        """
        if not texts:
            return []

        safe_texts = [t[:_MAX_CHARS] if t else "" for t in texts]

        if self._pipeline is not None:
            try:
                return self._run_transformer_batch(safe_texts)
            except Exception as exc:
                logger.warning(
                    "Transformer batch inference failed: %s. Using VADER.", exc
                )

        # Sequential VADER fallback
        return [
            self._run_vader(t) if t.strip() else SentimentResult(
                label=SentimentLabel.NEUTRAL, score=0.0, engine="vader"
            )
            for t in safe_texts
        ]

    # ── Analyse helpers ───────────────────────────────────────────────────

    def _run_transformer(self, text: str) -> SentimentResult:
        """Single-item transformer inference."""
        raw: List[List[Dict]] = self._pipeline(text)  # [[{label, score}, …]]
        return self._parse_transformer_output(raw[0])

    def _run_transformer_batch(self, texts: List[str]) -> List[SentimentResult]:
        """Batch transformer inference (single forward pass)."""
        raw_batch: List[List[Dict]] = self._pipeline(texts)
        return [self._parse_transformer_output(item) for item in raw_batch]

    def _parse_transformer_output(self, label_scores: List[Dict]) -> SentimentResult:
        """
        Normalise raw HuggingFace label→score dicts into a SentimentResult.

        Works with cardiffnlp (LABEL_0/1/2), distilbert (NEGATIVE/POSITIVE),
        and any model that follows the neg/neu/pos naming convention.
        """
        details: Dict[str, float] = {}
        for entry in label_scores:
            raw_label = entry["label"].lower()
            canonical = _LABEL_MAP.get(raw_label, raw_label)
            details[canonical] = entry["score"]

        # Ensure all three keys exist so downstream code is safe.
        details.setdefault("positive", 0.0)
        details.setdefault("neutral", 0.0)
        details.setdefault("negative", 0.0)

        dominant = max(details, key=details.get)
        label_enum = SentimentLabel(dominant) if dominant in SentimentLabel._value2member_map_ else SentimentLabel.NEUTRAL

        return SentimentResult(
            label=label_enum,
            score=details[dominant],
            details=details,
            engine="transformer",
        )

    def _run_vader(self, text: str) -> SentimentResult:
        """VADER-based sentiment analysis."""
        scores = self._vader.polarity_scores(text)
        compound = scores["compound"]

        details = {
            "positive": scores["pos"],
            "neutral":  scores["neu"],
            "negative": scores["neg"],
            "compound": compound,
        }

        if compound >= 0.05:
            label, score = SentimentLabel.POSITIVE, scores["pos"]
        elif compound <= -0.05:
            label, score = SentimentLabel.NEGATIVE, scores["neg"]
        else:
            label, score = SentimentLabel.NEUTRAL, scores["neu"]

        return SentimentResult(
            label=label,
            score=score,
            details=details,
            engine="vader",
        )

    # ── Utility ───────────────────────────────────────────────────────────

    def aggregate_sentiment(
        self, results: List[SentimentResult]
    ) -> Dict[str, float]:
        """
        Compute macro-averaged sentiment distribution across a list of results.

        Useful for summarising the overall tone of all comments on a post.

        Returns
        -------
        dict with keys: positive, neutral, negative, dominant_label
        """
        if not results:
            return {"positive": 0.0, "neutral": 1.0, "negative": 0.0, "dominant_label": "neutral"}

        totals: Dict[str, float] = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
        for r in results:
            totals["positive"] += r.details.get("positive", 0.0)
            totals["neutral"]  += r.details.get("neutral",  0.0)
            totals["negative"] += r.details.get("negative", 0.0)

        n = len(results)
        avg = {k: v / n for k, v in totals.items()}
        avg["dominant_label"] = max(
            ("positive", "neutral", "negative"), key=lambda k: avg[k]
        )
        return avg
