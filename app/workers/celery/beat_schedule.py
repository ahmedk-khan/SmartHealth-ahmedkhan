"""Periodic Celery task registry, kept separate from task implementations."""

BEAT_SCHEDULE = {
    "enqueue-due-appointment-reminders": {
        "task": "app.workers.celery.appointments.enqueue_due_appointment_reminders",
        "schedule": 900.0,
    },
    "publish-pending-events": {
        "task": "app.workers.celery.outbox.publish_pending_events",
        "schedule": 30.0,
    },
}
