"""Celery application factory.

Creates a Celery instance pre-configured with Redis broker/backend
from the central Settings.

This is the canonical Celery app used both by the FastAPI server (to
enqueue tasks via .delay()) and by the Celery worker process started
with:  celery -A app.core.celery_app worker
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

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
)
