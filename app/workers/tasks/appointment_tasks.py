import traceback

from app.celery_app import celery_app
from app.core.exceptions import AppError
from app.db import SessionLocal
from app.services.failed_job_service import FailedJobService
from app.services.notification_service import NotificationService


@celery_app.task(
    bind=True,
    name="app.workers.tasks.appointment_tasks.send_appointment_reminder",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_appointment_reminder(self, appointment_id: int) -> dict[str, object]:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        return service.send_appointment_reminder(appointment_id)
    except AppError as exc:
        failed_service = FailedJobService(db)
        failed_service.record_failure(
            task_name=self.name,
            task_id=self.request.id,
            exc=exc,
            payload={"appointment_id": appointment_id},
            traceback_text=traceback.format_exc(),
        )
        raise
    except Exception as exc:
        failed_service = FailedJobService(db)
        failed_service.record_failure(
            task_name=self.name,
            task_id=self.request.id,
            exc=exc,
            payload={"appointment_id": appointment_id},
            traceback_text=traceback.format_exc(),
        )
        if isinstance(exc, (ConnectionError, TimeoutError)):
            raise self.retry(exc=exc, countdown=30)
        raise
    finally:
        db.close()
