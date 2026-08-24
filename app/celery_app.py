from celery import Celery, signals
import logging

from app.core.settings import settings
from app.core.logging import set_correlation_id, set_request_id, configure_logging


celery_app = Celery(
    "smarthealth",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    imports=(
        "app.workers.tasks.appointment_tasks",
        "app.workers.tasks.analytics_tasks",
        "app.workers.tasks.outbox_tasks",
    ),
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
)

logger = logging.getLogger(__name__)


@signals.before_task_publish.connect
def before_task_publish(sender=None, body=None, **kwargs):
    """
    Attach correlation ID and request ID to task headers before publishing.
    This ensures correlation context is passed through task metadata.
    """
    from app.core.logging import get_correlation_id, get_request_id
    
    correlation_id = get_correlation_id()
    request_id = get_request_id()
    
    if body is not None:
        if correlation_id:
            body["headers"] = body.get("headers", {})
            body["headers"]["X-Correlation-ID"] = correlation_id
        if request_id:
            body["headers"] = body.get("headers", {})
            body["headers"]["X-Request-ID"] = request_id


@signals.task_prerun.connect
def task_prerun(sender=None, task_id=None, task=None, args=None, kwargs=None, **kw):
    """
    Extract correlation ID and request ID from task headers and set them in context.
    This runs before each task execution, establishing correlation context.
    """
    from app.core.logging import get_correlation_id, get_request_id
    from app.core.exceptions import generate_request_id
    
    # Try to get correlation ID and request ID from task headers
    headers = kw.get("headers", {}) or {}
    
    correlation_id = headers.get("X-Correlation-ID") or get_correlation_id() or generate_request_id()
    request_id = headers.get("X-Request-ID") or get_request_id() or task_id or generate_request_id()
    
    # Set in context for logging
    set_correlation_id(correlation_id)
    set_request_id(request_id)
    
    logger.info(
        "Task started",
        extra={
            "task_name": task.name if task else "unknown",
            "task_id": task_id,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
    )


@signals.task_postrun.connect
def task_postrun(sender=None, task_id=None, task=None, retval=None, state=None, **kwargs):
    """
    Log task completion with correlation context.
    """
    logger.info(
        "Task completed",
        extra={
            "task_name": task.name if task else "unknown",
            "task_id": task_id,
            "state": state,
        }
    )


@signals.task_failure.connect
def task_failure(sender=None, task_id=None, exception=None, args=None, traceback=None, **kwargs):
    """
    Log task failures with correlation context for debugging.
    """
    logger.error(
        "Task failed",
        extra={
            "task_name": sender.name if sender else "unknown",
            "task_id": task_id,
            "exception": str(exception),
        },
        exc_info=True
    )


# Configure logging for Celery worker
configure_logging()
