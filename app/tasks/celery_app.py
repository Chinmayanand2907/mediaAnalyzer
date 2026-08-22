"""
DEPRECATED — this module is no longer the canonical Celery application.

All Celery configuration, NLP model globals, and the worker_process_init
signal have been moved to ``app.core.celery_app``.

The worker must be started with:
    celery -A app.core.celery_app worker --loglevel=info

This file is kept only as a re-export shim to avoid ImportError from any
code that still references ``app.tasks.celery_app``.
"""

import warnings

warnings.warn(
    "app.tasks.celery_app is deprecated. "
    "Import from app.core.celery_app instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from the canonical location so existing imports don't break.
from app.core.celery_app import (  # noqa: E402, F401
    celery_app,
    _roberta_pipeline,
    _vader_analyzer,
    _use_vader,
)
