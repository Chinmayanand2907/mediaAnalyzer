"""Celery application factory.

Creates a Celery instance pre-configured with Redis broker/backend
from the central Settings.

This is the canonical Celery app used both by the FastAPI server (to
enqueue tasks via .delay()) and by the Celery worker process started
with:  celery -A app.core.celery_app worker

NLP Model Initialization
-------------------------
The ``@worker_process_init.connect`` signal loads the HuggingFace
RoBERTa sentiment pipeline **once per OS-level worker process**, so the
~500 MB model is shared across every task in that process rather than
being reloaded on every invocation.

Fallback strategy:
  - Primary:  cardiffnlp/twitter-roberta-base-sentiment-latest (transformers)
  - Fallback: vaderSentiment SentimentIntensityAnalyzer

Other modules import the globals from here:
    from app.core.celery_app import _roberta_pipeline, _vader_analyzer, _use_vader
"""

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import logging

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# ─── Celery Application ───────────────────────────────────────────────────────

celery_app = Celery(
    "engagement_analyzer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # Explicitly include the task modules so the worker picks them up
    include=["app.tasks.ingestion_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,           # hard kill after 1 hour
    task_soft_time_limit=3300,      # SIGTERM warning 5 min before hard kill
)

# ─── NLP Model Globals ────────────────────────────────────────────────────────
# Module-level so every task function in the same worker process can reference
# them without repeated disk I/O or GPU init.

_roberta_pipeline = None   # transformers Pipeline object (primary)
_vader_analyzer = None     # SentimentIntensityAnalyzer (fallback)
_use_vader: bool = False   # consumed by ingestion_tasks


# ─── Worker Process Init Signal ───────────────────────────────────────────────

@worker_process_init.connect
def _load_nlp_models(sender=None, **kwargs) -> None:
    """
    Load NLP models once per Celery worker *process* at startup.

    Celery spawns N worker processes (--concurrency N).  This signal fires
    exactly once inside each process right after it forks, so models are
    loaded into that process's private memory and shared by all tasks that
    execute within it — no redundant loads, no cross-process shared-memory
    issues.
    """
    global _roberta_pipeline, _vader_analyzer, _use_vader

    logger.info("[NLP Init] Loading sentiment model for worker process …")

    # ── Primary: Hugging Face RoBERTa ────────────────────────────────────────
    try:
        import os
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

        from transformers import pipeline  # type: ignore[import-untyped]

        _roberta_pipeline = pipeline(
            "sentiment-analysis",
            model="cardiffnlp/twitter-roberta-base-sentiment-latest",
            truncation=True,
            max_length=512,
            device="cpu",  # CPU ensures stability in forked Celery worker processes on macOS
        )
        _use_vader = False
        logger.info(
            "[NLP Init] ✅ RoBERTa pipeline loaded on CPU "
            "(cardiffnlp/twitter-roberta-base-sentiment-latest)."
        )

    # ── Fallback: VADER ───────────────────────────────────────────────────────
    except Exception as primary_exc:  # noqa: BLE001
        logger.warning(
            "[NLP Init] ⚠️  RoBERTa load failed (%s). Falling back to vaderSentiment.",
            primary_exc,
        )
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore

            _vader_analyzer = SentimentIntensityAnalyzer()
            _use_vader = True
            logger.info("[NLP Init] ✅ VADER SentimentIntensityAnalyzer loaded as fallback.")

        except Exception as fallback_exc:  # noqa: BLE001
            logger.error(
                "[NLP Init] ❌ VADER also failed (%s). "
                "Sentiment tasks will be non-operational until models are available.",
                fallback_exc,
            )
            _use_vader = False
