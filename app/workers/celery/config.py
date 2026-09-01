"""Celery broker and task configuration derived from application settings."""

from app.core.settings import settings

CELERY_BROKER_URL = settings.celery_broker_url
CELERY_RESULT_BACKEND = settings.celery_result_backend
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ALWAYS_EAGER = settings.celery_task_always_eager
