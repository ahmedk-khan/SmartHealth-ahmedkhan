"""Thin Temporal adapter for confirmation delivery.

Delivery failures are returned to the workflow as activity failures. The
workflow deliberately treats this activity as best-effort and continues.
"""

from temporalio import activity

from app.db.async_session import get_session
from app.repositories.notifications import NotificationDeliveryRepository
from app.services.notification_service import NotificationService


@activity.defn
async def send_confirmation_activity(user_id: int, appointment_id: int) -> dict[str, str | int]:
    if user_id <= 0 or appointment_id <= 0:
        raise ValueError("user_id and appointment_id must be positive")
    async with get_session() as session:
        return await NotificationService(session).send_confirmation(user_id, appointment_id)
