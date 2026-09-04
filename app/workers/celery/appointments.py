import datetime

from app.workers.celery_app import celery_app
from app.core.exceptions import AppError
from app.core.idempotency import idempotency_store
from app.db import SessionLocal
from app.repositories import AppointmentRepository
from app.services.notification_service import NotificationService
from app.workers.celery.task_helpers import run_notification_task


@celery_app.task(name="app.workers.celery.appointments.enqueue_due_appointment_reminders")
def enqueue_due_appointment_reminders() -> dict[str, int]:
    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        due = AppointmentRepository(db).iter_due_confirmed_reminders(now, now + datetime.timedelta(hours=24))
        enqueued = 0
        for appointment in due:
            send_appointment_reminder.delay(appointment.id)
            enqueued += 1
        return {"enqueued": enqueued}
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="app.workers.celery.appointments.send_appointment_reminder",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_appointment_reminder(self, appointment_id: int) -> dict[str, object]:
    def handler(db):
        appointment = AppointmentRepository(db).get_one_or_none_by_id(appointment_id)
        if appointment is None:
            raise AppError("Appointment not found", status_code=404, error_type="not_found", code="APPOINTMENT_NOT_FOUND")
        delivery_key = f"reminder:{appointment_id}:{appointment.slot.start_datetime.date().isoformat()}"
        if not idempotency_store.claim(appointment.patient_id, delivery_key, ttl_seconds=172800):
            return {"appointment_id": appointment_id, "status": "already_sent"}
        return NotificationService(db).send_appointment_reminder(appointment_id)

    return run_notification_task(
        self,
        appointment_id=appointment_id,
        metric_name="send_appointment_reminder",
        handler=handler,
    )


@celery_app.task(
    bind=True,
    name="app.workers.celery.appointments.send_visit_follow_up",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_visit_follow_up(self, appointment_id: int) -> dict[str, object]:
    return run_notification_task(
        self,
        appointment_id=appointment_id,
        metric_name="send_visit_follow_up",
        handler=lambda db: NotificationService(db).send_visit_follow_up(appointment_id),
    )
