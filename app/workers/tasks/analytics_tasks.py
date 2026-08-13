import traceback

from app.celery_app import celery_app
from app.core.exceptions import AppError
from app.db import SessionLocal
from app.services.analytics_service import AnalyticsService
from app.services.failed_job_service import FailedJobService


@celery_app.task(
    bind=True,
    name="app.workers.tasks.analytics_tasks.rollup_daily_analytics",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def rollup_daily_analytics(self, day: str | None = None) -> dict[str, object]:
    db = SessionLocal()
    try:
        service = AnalyticsService(db)
        return service.rollup_daily_metrics(day)
    except AppError as exc:
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
        failed_service = FailedJobService(db)
        failed_service.record_failure(
            task_name=self.name,
            task_id=self.request.id,
            exc=exc,
            payload={"day": day},
            traceback_text=traceback.format_exc(),
        )
        if isinstance(exc, (ConnectionError, TimeoutError)):
            raise self.retry(exc=exc, countdown=30)
        raise
    finally:
        db.close()
