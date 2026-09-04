import logging
import time
import traceback

from app.workers.celery_app import celery_app
from app.core.exceptions import AppError
from app.core.logging import get_correlation_id, get_request_id
from app.core.metrics import record_celery_task
from app.db import SessionLocal
from app.services.analytics_service import AnalyticsService
from app.services.failed_job_service import FailedJobService


logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.celery.analytics.rollup_daily_analytics",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def rollup_daily_analytics(self, day: str | None = None) -> dict[str, object]:
    """Rollup daily analytics with metrics tracking."""
    correlation_id = get_correlation_id()
    request_id = get_request_id()
    task_start_time = time.time()
    task_success = False
    
    logger.info(
        "Starting daily analytics rollup",
        extra={
            "task_id": self.request.id,
            "task_name": self.name,
            "day": day,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
    )
    
    db = SessionLocal()
    try:
        service = AnalyticsService(db)
        result = service.rollup_daily_metrics(day)
        task_success = True
        
        logger.info(
            "Daily analytics rollup completed",
            extra={
                "task_id": self.request.id,
                "day": day,
                "correlation_id": correlation_id,
            }
        )
        return result
    except AppError as exc:
        logger.error(
            "Daily analytics rollup failed with AppError",
            extra={
                "task_id": self.request.id,
                "day": day,
                "correlation_id": correlation_id,
                "error": str(exc),
            },
            exc_info=True
        )
        failed_service = FailedJobService(db)
        failed_service.record_failure(
            task_name=self.name,
            task_id=self.request.id,
            exc=exc,
            payload={"day": day},
            traceback_text=traceback.format_exc(),
        )
        raise
    except Exception as exc:
        logger.error(
            "Daily analytics rollup failed with exception",
            extra={
                "task_id": self.request.id,
                "day": day,
                "correlation_id": correlation_id,
                "error": str(exc),
            },
            exc_info=True
        )
        if isinstance(exc, (ConnectionError, TimeoutError)) and self.request.retries < self.max_retries:
            logger.info(
                "Retrying daily analytics rollup",
                extra={
                    "task_id": self.request.id,
                    "day": day,
                    "retry_count": self.request.retries,
                }
            )
            raise self.retry(exc=exc, countdown=30)
        failed_service = FailedJobService(db)
        failed_service.record_failure(
            task_name=self.name,
            task_id=self.request.id,
            exc=exc,
            payload={"day": day},
            traceback_text=traceback.format_exc(),
        )
        raise
    finally:
        db.close()
        
        # Record task metrics
        try:
            task_duration = time.time() - task_start_time
            record_celery_task(
                task_name="rollup_daily_analytics",
                success=task_success,
                duration_seconds=task_duration
            )
        except Exception as exc:
            logger.error(f"Failed to record Celery task metric: {exc}", exc_info=True)
