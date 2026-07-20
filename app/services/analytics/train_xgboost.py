"""
XGBoost Growth-Velocity Prediction — Training Script.

This module trains a regression model that predicts the ``growth_velocity``
of a social-media channel / subreddit based on its subscriber count and NLP
sentiment scores stored in PostgreSQL.

Usage
-----
Run as a standalone script from the project root::

    python -m app.services.analytics.train_xgboost

Or import and call programmatically::

    from app.services.analytics.train_xgboost import train_and_save_model
    metrics = train_and_save_model()

Output
------
Trained model saved to:  app/models/registry/xgboost_model.pkl

Model Artifact
--------------
The saved artifact is a plain dict with two keys so callers can load both
the model and the feature-column order without guessing::

    {
        "model":    XGBRegressor (fitted),
        "features": list[str],   # column order expected at inference time
    }

Schema Contract
---------------
Reads ``platform_accounts`` table.  Rows are skipped if
``extra_metadata`` is NULL or does not contain a ``sentiment`` sub-key
(i.e., the sentiment task has not yet been run for that account).

Feature Engineering
-------------------
    growth_velocity = subscriber_count / max(days_since_created, 1)

This represents the average daily subscriber growth since the account was
first tracked.  It serves as a proxy for channel momentum and is the
regression target.

Predictors
    - subscriber_count      (current known count)
    - positive_pct          (from sentiment analysis)
    - neutral_pct
    - negative_pct
    - total_comments_analyzed
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import select

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

# Resolve relative to this file so the script works regardless of CWD.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_OUTPUT_PATH = _PROJECT_ROOT / "app" / "models" / "registry" / "xgboost_model.pkl"

# ─── Feature & Target Definitions ────────────────────────────────────────────

FEATURE_COLUMNS = [
    "subscriber_count",
    "positive_pct",
    "neutral_pct",
    "negative_pct",
    "total_comments_analyzed",
]
TARGET_COLUMN = "growth_velocity"


# ─── Data Loading ─────────────────────────────────────────────────────────────

async def _fetch_training_rows_async() -> list[dict]:
    """
    Query PostgreSQL for all PlatformAccount rows that carry sentiment data.

    Returns a list of flat dicts ready for DataFrame construction.
    """
    # Import here to avoid module-level side-effects when the file is imported
    # in a non-Django / non-FastAPI context (e.g. a standalone training job).
    from app.db.postgres import AsyncSessionLocal, PlatformAccount  # noqa: PLC0415

    rows: list[dict] = []

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PlatformAccount))
        accounts = result.scalars().all()

    for account in accounts:
        # Skip rows without sentiment data
        if not account.extra_metadata:
            continue

        try:
            meta = json.loads(account.extra_metadata)
        except json.JSONDecodeError:
            logger.warning(
                "Skipping account %s/%s — malformed extra_metadata JSON.",
                account.platform,
                account.platform_id,
            )
            continue

        sentiment = meta.get("sentiment")
        if not sentiment:
            # Sentiment task has not run yet for this account.
            continue

        # ── Feature Engineering: growth_velocity ────────────────────────────
        # Use timezone-naive UTC now to match the stored created_at column.
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        created_at = account.created_at  # already timezone-naive per postgres.py

        # Guard: ensure created_at is a datetime object (not None / str)
        if not isinstance(created_at, datetime):
            continue

        days_alive = max((now_utc - created_at).days, 1)
        subscriber_count = account.subscriber_count or 0
        growth_velocity = subscriber_count / days_alive

        rows.append(
            {
                "platform":                account.platform,
                "platform_id":             account.platform_id,
                "subscriber_count":        subscriber_count,
                "positive_pct":            float(sentiment.get("positive_pct", 0.0)),
                "neutral_pct":             float(sentiment.get("neutral_pct", 0.0)),
                "negative_pct":            float(sentiment.get("negative_pct", 0.0)),
                "total_comments_analyzed": int(sentiment.get("total_comments_analyzed", 0)),
                TARGET_COLUMN:             growth_velocity,
            }
        )

    return rows


def _load_training_dataframe() -> pd.DataFrame:
    """
    Synchronous wrapper: run the async DB query and return a DataFrame.

    Raises
    ------
    ValueError
        If fewer than 2 rows are returned (can't do a meaningful train/test
        split with a single data point).
    """
    rows = asyncio.run(_fetch_training_rows_async())

    if len(rows) < 2:
        raise ValueError(
            f"Insufficient training data: only {len(rows)} row(s) with sentiment data "
            "found in PostgreSQL.  Run the ingestion and sentiment tasks first."
        )

    df = pd.DataFrame(rows)
    logger.info("Loaded %d training rows from PostgreSQL.", len(df))
    logger.debug("Sample data:\n%s", df[FEATURE_COLUMNS + [TARGET_COLUMN]].head())
    return df


# ─── Training ─────────────────────────────────────────────────────────────────

def _build_and_train(df: pd.DataFrame) -> tuple:
    """
    Engineer features, split data, train XGBRegressor, return (model, rmse).

    XGBoost and scikit-learn are imported lazily here so the module can be
    imported on macOS machines where libomp is not yet installed without
    raising an immediate ImportError at module load time.
    """
    # Lazy imports — only fail at call-time, not at module load time.
    try:
        from xgboost import XGBRegressor  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise ImportError(
            "XGBoost could not be loaded. On macOS run `brew install libomp` "
            f"then restart Python.\nOriginal error: {e}"
        ) from e
    from sklearn.metrics import mean_squared_error  # noqa: PLC0415
    from sklearn.model_selection import train_test_split  # noqa: PLC0415

    X = df[FEATURE_COLUMNS].copy()
    y = df[TARGET_COLUMN].copy()

    # 80 / 20 stratified split (random_state for reproducibility)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = XGBRegressor(
        n_estimators=100,
        learning_rate=0.1,
        max_depth=5,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0,          # suppress XGBoost's own logging
        n_jobs=-1,            # use all available CPU cores
    )

    logger.info(
        "Training XGBRegressor on %d samples (%d features) …",
        len(X_train),
        len(FEATURE_COLUMNS),
    )
    model.fit(X_train, y_train)

    # Evaluate on held-out test set
    y_pred = model.predict(X_test)
    rmse = float(mean_squared_error(y_test, y_pred) ** 0.5)
    logger.info("Test RMSE: %.4f (growth_velocity subscribers/day)", rmse)

    return model, rmse


# ─── Public API ───────────────────────────────────────────────────────────────

def train_and_save_model(output_path: str | Path | None = None) -> dict:
    """
    End-to-end training pipeline: load → train → evaluate → save.

    Parameters
    ----------
    output_path : str or Path, optional
        Where to write the joblib artifact.  Defaults to
        ``app/models/registry/xgboost_model.pkl`` (relative to project root).

    Returns
    -------
    dict
        ``{"rmse": float, "n_samples": int, "model_path": str}``
    """
    save_path = Path(output_path) if output_path else MODEL_OUTPUT_PATH
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Load data ────────────────────────────────────────────────────────────
    df = _load_training_dataframe()

    # ── Train ────────────────────────────────────────────────────────────────
    model, rmse = _build_and_train(df)

    # ── Save ─────────────────────────────────────────────────────────────────
    # Bundle the model with its expected feature columns so inference code
    # can reconstruct the correct input DataFrame column order.
    artifact = {
        "model": model,
        "features": FEATURE_COLUMNS,
        "target": TARGET_COLUMN,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": len(df),
        "test_rmse": rmse,
    }
    joblib.dump(artifact, save_path)
    logger.info("Model artifact saved → %s", save_path)

    return {
        "rmse": rmse,
        "n_samples": len(df),
        "model_path": str(save_path),
    }


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        stream=sys.stdout,
    )

    print("=" * 60)
    print(" XGBoost Growth-Velocity Training Script")
    print("=" * 60)

    try:
        metrics = train_and_save_model()
        print(f"\n✅  Training complete!")
        print(f"    Samples  : {metrics['n_samples']}")
        print(f"    RMSE     : {metrics['rmse']:.4f} subscribers/day")
        print(f"    Saved to : {metrics['model_path']}")
    except ValueError as e:
        print(f"\n⚠️  {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌  Training failed: {e}")
        raise
