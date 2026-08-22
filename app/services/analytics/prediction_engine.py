"""
Prediction Engine
=================
Forecasts engagement metrics for the next N upcoming posts using a historical
feature matrix built from MongoDB raw data + PostgreSQL metrics.

Architecture
------------
1. **Preprocessing pipeline** — converts raw JSON documents (engagement metrics
   + sentiment scores) into a clean, numeric Pandas DataFrame with temporal and
   lag features.
2. **XGBoost inference wrapper** — loads a pre-trained XGBoost model and runs
   multi-step iterative forecasting.  If XGBoost cannot be loaded (e.g., the
   system is missing the ``libomp`` OpenMP runtime on macOS), the engine falls
   back to a transparent moving-average baseline so the rest of the application
   keeps working.
3. **Training helper** — lightweight in-process training for initial model
   creation or periodic re-training.

Fixing XGBoost on macOS
-----------------------
XGBoost requires the OpenMP runtime::

    brew install libomp          # Homebrew (recommended)

After installation restart the Python process.

Usage
-----
    from app.services.analytics.prediction_engine import PredictionEngine

    engine = PredictionEngine()

    historical = [
        {
            "published_at": "2026-06-01T10:00:00Z",
            "engagement_metrics": {"views": 5000, "likes": 300, "comments": 40},
            "sentiment": {"positive": 0.7, "neutral": 0.2, "negative": 0.1},
        },
        # … more records …
    ]

    forecasts = engine.forecast_next_posts(historical, num_posts=5)
    # [{"forecast_step": 1, "predicted_views": 5200.0, ...}, ...]
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Optional XGBoost import ───────────────────────────────────────────────────

_XGBOOST_AVAILABLE = False
_xgb: Any = None

try:
    import xgboost as xgb_module

    _xgb = xgb_module
    _XGBOOST_AVAILABLE = True
    logger.info("XGBoost %s loaded successfully.", xgb_module.__version__)
except Exception as _xgb_err:
    warnings.warn(
        f"XGBoost could not be imported ({_xgb_err}). "
        "PredictionEngine will use a moving-average baseline instead. "
        "On macOS run `brew install libomp` then restart Python.",
        RuntimeWarning,
        stacklevel=2,
    )


# ── Feature engineering constants ────────────────────────────────────────────

# Engagement columns we want to model.
_ENGAGEMENT_COLS = ["views", "likes", "comments", "shares", "saves"]

# Sentiment columns we expect after flattening.
_SENTIMENT_COLS = ["sentiment_positive", "sentiment_neutral", "sentiment_negative"]

# Number of lag steps to create for time-series modelling.
_DEFAULT_LAG_STEPS = 5

# Rolling window sizes for rolling statistics.
_ROLLING_WINDOWS = [3, 5]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ForecastResult:
    """Single-step forecast output."""

    forecast_step: int
    predicted_views: float
    predicted_likes: float
    predicted_comments: float
    confidence_interval: Tuple[float, float]   # (lower, upper) for views
    engine: str = "unknown"

    def to_dict(self) -> Dict:
        return {
            "forecast_step":       self.forecast_step,
            "predicted_views":     round(max(0.0, self.predicted_views), 1),
            "predicted_likes":     round(max(0.0, self.predicted_likes), 1),
            "predicted_comments":  round(max(0.0, self.predicted_comments), 1),
            "confidence_interval": [
                round(max(0.0, self.confidence_interval[0]), 1),
                round(max(0.0, self.confidence_interval[1]), 1),
            ],
            "engine": self.engine,
        }


# ── Preprocessing pipeline ────────────────────────────────────────────────────

class FeaturePipeline:
    """
    Transforms raw historical records (dicts from MongoDB / Postgres) into a
    clean numeric DataFrame suitable for XGBoost or any sklearn-compatible model.

    Expected input record shape::

        {
            "published_at":      "2026-06-18T10:00:00Z",   # ISO-8601 string or datetime
            "engagement_metrics": {
                "views": 10000, "likes": 500, "comments": 80,
                "shares": 30,   "saves": 120             # optional
            },
            "sentiment": {
                "positive": 0.65, "neutral": 0.25, "negative": 0.10
            },
            "topic_encoded":     3                         # optional int label
        }
    """

    def __init__(self, lag_steps: int = _DEFAULT_LAG_STEPS) -> None:
        self.lag_steps = lag_steps
        self._fitted_columns: Optional[List[str]] = None

    # ── Public methods ────────────────────────────────────────────────────

    def fit_transform(self, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """Full pipeline: flatten → temporal → lags → rolling stats → finalise."""
        df = self._flatten(records)
        df = self._temporal_features(df)
        df = self._lag_features(df)
        df = self._rolling_features(df)
        df = self._finalise(df)
        self._fitted_columns = df.columns.tolist()
        return df

    def transform(self, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Transform new records using the same column set learned during
        `fit_transform`.  Call this when preparing data for inference only.
        """
        df = self._flatten(records)
        df = self._temporal_features(df)
        df = self._lag_features(df)
        df = self._rolling_features(df)
        df = self._finalise(df)

        if self._fitted_columns:
            # Align to training columns; fill missing with 0.
            df = df.reindex(columns=self._fitted_columns, fill_value=0)

        return df

    # ── Private helpers ───────────────────────────────────────────────────

    def _flatten(self, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """Flatten nested dicts and build a flat DataFrame."""
        if not records:
            return pd.DataFrame()

        rows = []
        for rec in records:
            flat: Dict[str, Any] = {}

            # Temporal
            flat["published_at"] = rec.get("published_at")

            # Engagement metrics
            eng = rec.get("engagement_metrics") or rec.get("engagement") or {}
            for col in _ENGAGEMENT_COLS:
                flat[col] = float(eng.get(col, 0.0))

            # Sentiment scores
            sent = rec.get("sentiment") or {}
            flat["sentiment_positive"] = float(sent.get("positive", 0.0))
            flat["sentiment_neutral"]  = float(sent.get("neutral",  0.0))
            flat["sentiment_negative"] = float(sent.get("negative", 0.0))

            # Optional topic label (categorical → int)
            flat["topic_encoded"] = int(rec.get("topic_encoded", 0))

            rows.append(flat)

        return pd.DataFrame(rows)

    @staticmethod
    def _temporal_features(df: pd.DataFrame) -> pd.DataFrame:
        """Extract day-of-week and hour-of-day from the published_at column."""
        if "published_at" not in df.columns:
            return df

        df = df.copy()
        ts = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
        df["day_of_week"]  = ts.dt.dayofweek.fillna(0).astype(int)
        df["hour_of_day"]  = ts.dt.hour.fillna(12).astype(int)
        df["month"]        = ts.dt.month.fillna(1).astype(int)
        df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)
        df = df.drop(columns=["published_at"], errors="ignore")
        return df

    def _lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create lagged copies of engagement and sentiment columns."""
        if df.empty:
            return df

        target_cols = [
            c for c in df.columns
            if c in _ENGAGEMENT_COLS + _SENTIMENT_COLS
        ]

        lagged = df.copy()
        for lag in range(1, self.lag_steps + 1):
            for col in target_cols:
                lagged[f"{col}_lag{lag}"] = lagged[col].shift(lag)

        lagged = lagged.dropna().reset_index(drop=True)
        return lagged

    @staticmethod
    def _rolling_features(df: pd.DataFrame) -> pd.DataFrame:
        """Add rolling mean and std for engagement columns."""
        if df.empty:
            return df

        result = df.copy()
        for window in _ROLLING_WINDOWS:
            for col in _ENGAGEMENT_COLS:
                if col in result.columns:
                    result[f"{col}_roll{window}_mean"] = (
                        result[col].rolling(window, min_periods=1).mean()
                    )
                    result[f"{col}_roll{window}_std"] = (
                        result[col].rolling(window, min_periods=1).std().fillna(0)
                    )
        return result

    @staticmethod
    def _finalise(df: pd.DataFrame) -> pd.DataFrame:
        """Keep only numeric columns and fill remaining NaNs."""
        df = df.fillna(0)
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        return df[numeric_cols]


# ── Prediction engine ─────────────────────────────────────────────────────────

class PredictionEngine:
    """
    Wraps a trained XGBoost model (or a baseline) and exposes a single
    `forecast_next_posts` method to the rest of the application.

    Parameters
    ----------
    model_path:
        Optional path to a saved XGBoost model file (.ubj / .json / .model).
        If None the engine starts without a model and uses the moving-average
        baseline until `train()` is called or a model is loaded via
        `load_model()`.
    lag_steps:
        Number of lag features the pipeline should create (must match whatever
        value was used at training time).
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        lag_steps: int = _DEFAULT_LAG_STEPS,
    ) -> None:
        self.model_path = model_path
        self.pipeline = FeaturePipeline(lag_steps=lag_steps)
        self._model: Any = None   # xgb.Booster | None
        self._target_col = "views"

        if model_path:
            self.load_model(model_path)

    # ── Model persistence ─────────────────────────────────────────────────

    def load_model(self, path: str) -> bool:
        """
        Load a persisted XGBoost Booster from *path*.

        Returns True on success, False on failure.
        """
        if not _XGBOOST_AVAILABLE:
            logger.error("Cannot load model — XGBoost is not available.")
            return False
        try:
            booster = _xgb.Booster()
            booster.load_model(path)
            self._model = booster
            self.model_path = path
            logger.info("XGBoost model loaded from '%s'.", path)
            return True
        except Exception as exc:
            logger.error("Failed to load XGBoost model from '%s': %s", path, exc)
            return False

    def save_model(self, path: str) -> bool:
        """Persist the current model to *path*.  Returns True on success."""
        if self._model is None:
            logger.warning("No model to save.")
            return False
        try:
            self._model.save_model(path)
            logger.info("Model saved to '%s'.", path)
            return True
        except Exception as exc:
            logger.error("Failed to save model: %s", exc)
            return False

    # ── Training ──────────────────────────────────────────────────────────

    def train(
        self,
        records: List[Dict[str, Any]],
        target_col: str = "views",
        num_boost_round: int = 100,
        params: Optional[Dict[str, Any]] = None,
        save_path: Optional[str] = None,
    ) -> bool:
        """
        Train an XGBoost model in-process from *records*.

        This is suitable for scheduled re-training jobs triggered by Celery.
        For large datasets, train offline and use `load_model()` instead.

        Parameters
        ----------
        records:
            Same structure as `forecast_next_posts`.
        target_col:
            The engagement metric to model (default: "views").
        num_boost_round:
            Number of XGBoost boosting rounds.
        params:
            XGBoost hyper-parameters.  Sensible defaults are provided.
        save_path:
            If given, the model is saved here after training.

        Returns
        -------
        bool: True on success.
        """
        if not _XGBOOST_AVAILABLE:
            logger.error("XGBoost unavailable — training skipped.")
            return False

        if len(records) < _DEFAULT_LAG_STEPS + 2:
            logger.warning(
                "Not enough records to train (%d). Need at least %d.",
                len(records), _DEFAULT_LAG_STEPS + 2,
            )
            return False

        try:
            df = self.pipeline.fit_transform(records)

            if target_col not in df.columns:
                logger.error("Target column '%s' not found after preprocessing.", target_col)
                return False

            y = df[target_col].values
            X = df.drop(columns=[target_col], errors="ignore").values

            dtrain = _xgb.DMatrix(X, label=y)

            default_params: Dict[str, Any] = {
                "objective":        "reg:squarederror",
                "eval_metric":      "rmse",
                "eta":              0.05,
                "max_depth":        6,
                "subsample":        0.8,
                "colsample_bytree": 0.8,
                "min_child_weight": 3,
                "seed":             42,
            }
            if params:
                default_params.update(params)

            self._model = _xgb.train(
                default_params,
                dtrain,
                num_boost_round=num_boost_round,
                verbose_eval=False,
            )
            self._target_col = target_col

            logger.info(
                "XGBoost model trained — %d records, %d features, %d rounds.",
                len(records), X.shape[1], num_boost_round,
            )

            if save_path:
                self.save_model(save_path)

            return True
        except Exception as exc:
            logger.error("Training failed: %s", exc)
            return False

    # ── Inference ─────────────────────────────────────────────────────────

    def forecast_next_posts(
        self,
        recent_history: List[Dict[str, Any]],
        num_posts: int = 5,
    ) -> List[Dict]:
        """
        Forecast engagement metrics for the next *num_posts* posts.

        The forecast is *iterative*: after each step the predicted values are
        fed back as inputs for the subsequent step.

        Parameters
        ----------
        recent_history:
            Ordered list of historical post records (oldest → newest).
            Minimum length: lag_steps + 1.
        num_posts:
            How many future posts to forecast (default: 5).

        Returns
        -------
        List[dict] — one ForecastResult.to_dict() per forecast step.
        """
        if not recent_history:
            logger.warning("forecast_next_posts called with empty history.")
            return []

        logger.info(
            "Forecasting %d posts using %s engine (%d history records).",
            num_posts,
            "xgboost" if (self._model and _XGBOOST_AVAILABLE) else "baseline",
            len(recent_history),
        )

        try:
            feature_df = self.pipeline.fit_transform(recent_history)
        except Exception as exc:
            logger.error("Feature pipeline failed: %s", exc)
            return []

        if feature_df.empty:
            logger.warning("Feature pipeline returned an empty DataFrame.")
            return []

        if self._model and _XGBOOST_AVAILABLE:
            return self._xgboost_forecast(feature_df, recent_history, num_posts)
        else:
            return self._baseline_forecast(recent_history, num_posts)

    # ── Internal forecast strategies ──────────────────────────────────────

    def _xgboost_forecast(
        self,
        feature_df: pd.DataFrame,
        raw_history: List[Dict],
        num_posts: int,
    ) -> List[Dict]:
        """Multi-step iterative XGBoost forecast."""
        predictions: List[Dict] = []
        working_history = list(raw_history)  # mutable copy

        for step in range(1, num_posts + 1):
            try:
                df = self.pipeline.transform(working_history)
                if df.empty:
                    break

                target_col = self._target_col
                feature_cols = [c for c in df.columns if c != target_col]
                X_latest = df[feature_cols].iloc[[-1]].values

                dmatrix = _xgb.DMatrix(X_latest)
                pred_views = float(self._model.predict(dmatrix)[0])

                # Derive correlated metrics using historical ratios
                avg_ratio = self._engagement_ratios(working_history)
                pred_likes    = pred_views * avg_ratio.get("likes_per_view",    0.06)
                pred_comments = pred_views * avg_ratio.get("comments_per_view", 0.008)

                ci_low  = pred_views * 0.80
                ci_high = pred_views * 1.20

                result = ForecastResult(
                    forecast_step=step,
                    predicted_views=pred_views,
                    predicted_likes=pred_likes,
                    predicted_comments=pred_comments,
                    confidence_interval=(ci_low, ci_high),
                    engine="xgboost",
                )
                predictions.append(result.to_dict())

                # Feed prediction back as a synthetic record for next step
                working_history.append(
                    self._synthetic_record(pred_views, pred_likes, pred_comments)
                )
            except Exception as exc:
                logger.error("XGBoost step %d failed: %s. Falling back.", step, exc)
                # Fall through to baseline for remaining steps
                baseline_remaining = self._baseline_forecast(
                    working_history, num_posts - step + 1
                )
                # Use enumerate so each remaining step gets a unique sequential number
                for idx, br in enumerate(baseline_remaining, start=1):
                    br["forecast_step"] = len(predictions) + idx
                    predictions.append(br)
                break

        return predictions

    def _baseline_forecast(
        self,
        history: List[Dict],
        num_posts: int,
    ) -> List[Dict]:
        """
        Simple moving-average baseline used when XGBoost is unavailable or
        has not been trained yet.

        Uses the last min(5, len(history)) records to compute the mean of each
        engagement metric and adds ±5% random walk noise for realism.
        """
        window = min(5, len(history))
        recent = history[-window:]

        def _mean(key: str) -> float:
            vals = [
                float((r.get("engagement_metrics") or {}).get(key, 0))
                for r in recent
            ]
            return float(np.mean(vals)) if vals else 0.0

        base_views    = _mean("views")
        base_likes    = _mean("likes")
        base_comments = _mean("comments")

        results: List[Dict] = []
        for step in range(1, num_posts + 1):
            noise = np.random.uniform(0.95, 1.05)
            pv = max(0.0, base_views    * noise * (1 + step * 0.01))
            pl = max(0.0, base_likes    * noise * (1 + step * 0.01))
            pc = max(0.0, base_comments * noise * (1 + step * 0.01))

            result = ForecastResult(
                forecast_step=step,
                predicted_views=pv,
                predicted_likes=pl,
                predicted_comments=pc,
                confidence_interval=(pv * 0.80, pv * 1.20),
                engine="baseline_moving_avg",
            )
            results.append(result.to_dict())

        return results

    # ── Utility helpers ───────────────────────────────────────────────────

    @staticmethod
    def _engagement_ratios(history: List[Dict]) -> Dict[str, float]:
        """Compute average likes-per-view and comments-per-view ratios."""
        likes_ratios: List[float] = []
        comment_ratios: List[float] = []

        for rec in history:
            eng = rec.get("engagement_metrics") or {}
            views = float(eng.get("views", 0))
            if views > 0:
                likes_ratios.append(float(eng.get("likes", 0)) / views)
                comment_ratios.append(float(eng.get("comments", 0)) / views)

        return {
            "likes_per_view":    float(np.mean(likes_ratios))    if likes_ratios    else 0.06,
            "comments_per_view": float(np.mean(comment_ratios))  if comment_ratios  else 0.008,
        }

    @staticmethod
    def _synthetic_record(
        pred_views: float,
        pred_likes: float,
        pred_comments: float,
    ) -> Dict[str, Any]:
        """Build a minimal synthetic history record from a forecast result."""
        return {
            "published_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "engagement_metrics": {
                "views":    pred_views,
                "likes":    pred_likes,
                "comments": pred_comments,
                "shares":   0.0,
                "saves":    0.0,
            },
            "sentiment": {"positive": 0.5, "neutral": 0.4, "negative": 0.1},
            "topic_encoded": 0,
        }
