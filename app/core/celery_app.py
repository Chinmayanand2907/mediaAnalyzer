"""Celery application factory.

Creates a Celery instance pre-configured with Redis broker/backend
from the central Settings.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "engagement_analyzer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Auto-discover tasks inside each sub-package
    task_routes={
        "app.services.youtube.tasks.*": {"queue": "youtube"},
        "app.services.reddit.tasks.*": {"queue": "reddit"},
    },
)

# Auto-discover task modules
celery_app.autodiscover_tasks(["app.services.youtube", "app.services.reddit"])
