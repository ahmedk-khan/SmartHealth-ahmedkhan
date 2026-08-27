import logging
import time
import traceback
import datetime

from app.celery_app import celery_app
from app.core.exceptions import AppError
from app.core.logging import get_correlation_id, get_request_id
from app.core.metrics import record_celery_task
from app.db import SessionLocal
from app.services.failed_job_service import FailedJobService
from app.services.notification_service import NotificationService
from app.models import Appointment, AppointmentStatus, Slot
from app.core.idempotency import idempotency_store


logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.appointment_tasks.enqueue_due_appointment_reminders")
def enqueue_due_appointment_reminders() -> dict[str, int]:
    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        due = db.query(Appointment).join(Slot).filter(
            Appointment.status == AppointmentStatus.CONFIRMED,
            Slot.start_datetime >= now,
            Slot.start_datetime <= now + datetime.timedelta(hours=24),
        ).all()
        for appointment in due:
            send_appointment_reminder.delay(appointment.id)
        return {"enqueued": len(due)}
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.appointment_tasks.send_appointment_reminder",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_appointment_reminder(self, appointment_id: int) -> dict[str, object]:
    """
    Send an appointment reminder notification.
    
    This task is executed asynchronously via Celery, with automatic
    correlation ID propagation from task headers.
    
    Args:
        appointment_id: ID of the appointment to send reminder for
    
    Returns:
        Dictionary with task result
    """
    correlation_id = get_correlation_id()
    request_id = get_request_id()
    task_start_time = time.time()
    
    logger.info(
        "Starting appointment reminder task",
        extra={
            "task_id": self.request.id,
            "task_name": self.name,
            "appointment_id": appointment_id,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
    )
    
    db = SessionLocal()
    task_success = False
    try:
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).one_or_none()
        if appointment is None:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")
        delivery_key = f"reminder:{appointment_id}:{appointment.slot.start_datetime.date().isoformat()}"
        if not idempotency_store.claim(appointment.patient_id, delivery_key, ttl_seconds=172800):
            return {"appointment_id": appointment_id, "status": "already_sent"}
        service = NotificationService(db)
        result = service.send_appointment_reminder(appointment_id)
        task_success = True
        
        logger.info(
            "Appointment reminder sent successfully",
            extra={
                "task_id": self.request.id,
                "appointment_id": appointment_id,
                "correlation_id": correlation_id,
            }
        )
        
        return result
    except AppError as exc:
        logger.error(
            "Appointment reminder task failed with AppError",
            extra={
                "task_id": self.request.id,
                "appointment_id": appointment_id,
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
            payload={"appointment_id": appointment_id},
            traceback_text=traceback.format_exc(),
        )
        raise
    except Exception as exc:
        logger.error(
            "Appointment reminder task failed with exception",
            extra={
                "task_id": self.request.id,
                "appointment_id": appointment_id,
                "correlation_id": correlation_id,
                "error": str(exc),
            },
            exc_info=True
        )
        
        if isinstance(exc, (ConnectionError, TimeoutError)) and self.request.retries < self.max_retries:
            logger.info(
                "Retrying appointment reminder task",
                extra={
                    "task_id": self.request.id,
                    "appointment_id": appointment_id,
                    "retry_count": self.request.retries,
                }
            )
            raise self.retry(exc=exc, countdown=30)
        failed_service = FailedJobService(db)
        failed_service.record_failure(
            task_name=self.name,
            task_id=self.request.id,
            exc=exc,
            payload={"appointment_id": appointment_id},
            traceback_text=traceback.format_exc(),
        )
        raise
    finally:
        db.close()
        
        # Record task metrics
        try:
            task_duration = time.time() - task_start_time
            record_celery_task(
                task_name="send_appointment_reminder",
                success=task_success,
                duration_seconds=task_duration
            )
        except Exception as exc:
            logger.error(f"Failed to record Celery task metric: {exc}", exc_info=True)
        
        logger.info(
            "Appointment reminder task completed",
            extra={
                "task_id": self.request.id,
                "appointment_id": appointment_id,
                "correlation_id": correlation_id,
            }
        )
