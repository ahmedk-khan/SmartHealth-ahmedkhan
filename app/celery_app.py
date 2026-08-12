from celery import Celery

from app.core.settings import settings


celery_app = Celery(
    "smarthealth",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    imports=("app.tasks",),
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)
