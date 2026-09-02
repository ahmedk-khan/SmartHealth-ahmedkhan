from app.core.exceptions import NotFoundError
import datetime

from app.models import Appointment, Notification, NotificationStatus
from app.repositories.appointments import AppointmentRepository
from app.repositories.notifications import NotificationRepository
from app.services.base import BaseService


class NotificationService(BaseService):
    def __init__(self, db):
        super().__init__(db)
        self.notifications = NotificationRepository(db)
        self.appointments = AppointmentRepository(db)

    def create_follow_up(self, appointment: Appointment) -> Notification:
        notification = Notification(
            user_id=appointment.patient.user_id,
            type="VISIT_FOLLOW_UP",
            payload={"appointment_id": appointment.id, "channel": "email"},
            status=NotificationStatus.PENDING,
        )
        return self.notifications.add_and_refresh(notification)

    def schedule_appointment_reminder(self, appointment_id: int) -> Notification:
        existing = self.notifications.get_reminder(appointment_id)
        if existing:
            return existing
        appointment = self.appointments.get_by_id_or_none(appointment_id)
        if appointment is None:
            raise NotFoundError("Appointment not found", code="APPOINTMENT_NOT_FOUND")
        notification = Notification(
            user_id=appointment.patient.user_id,
            type="APPOINTMENT_REMINDER",
            payload={"appointment_id": appointment.id, "channel": "email"},
            status=NotificationStatus.PENDING,
        )
        return self.notifications.add_and_refresh(notification)

    def cancel_notification(self, notification_id: int) -> Notification | None:
        notification = self.notifications.get_by_id_for_update(notification_id)
        if notification is None or notification.status == NotificationStatus.CANCELLED:
            return notification
        if notification.status == NotificationStatus.SENT:
            return notification
        return self.notifications.cancel(notification)

    def send_appointment_reminder(self, appointment_id: int) -> dict[str, object]:
        appointment = self.appointments.get_by_id_or_none(appointment_id)
        if appointment is None:
            raise NotFoundError("Appointment not found", code="APPOINTMENT_NOT_FOUND")

        notification = self.schedule_appointment_reminder(appointment_id)
        if notification.status == NotificationStatus.CANCELLED:
            return {"appointment_id": appointment.id, "status": "cancelled", "notification_id": notification.id}
        if notification.status == NotificationStatus.SENT:
            return {
                "appointment_id": appointment.id,
                "patient_id": appointment.patient_id,
                "provider_id": appointment.provider_id,
                "status": "already_sent",
                "channel": "email",
                "notification_id": notification.id,
            }
        self.notifications.mark_sent(notification)
        return {
            "appointment_id": appointment.id,
            "patient_id": appointment.patient_id,
            "provider_id": appointment.provider_id,
            "status": "sent",
            "channel": "email",
            "notification_id": notification.id,
        }

    def send_visit_follow_up(self, appointment_id: int) -> dict[str, object]:
        appointment = self.appointments.get_by_id_or_none(appointment_id)
        if appointment is None:
            raise NotFoundError("Appointment not found", code="APPOINTMENT_NOT_FOUND")

        notification = self.notifications.get_follow_up(appointment_id)
        if notification is None:
            notification = self.create_follow_up(appointment)

        if notification.status == NotificationStatus.CANCELLED:
            return {"appointment_id": appointment.id, "status": "cancelled", "notification_id": notification.id}
        if notification.status == NotificationStatus.SENT:
            return {
                "appointment_id": appointment.id,
                "patient_id": appointment.patient_id,
                "provider_id": appointment.provider_id,
                "status": "already_sent",
                "channel": "email",
                "notification_id": notification.id,
            }
        
        self.notifications.mark_sent(notification)
        return {
            "appointment_id": appointment.id,
            "patient_id": appointment.patient_id,
            "provider_id": appointment.provider_id,
            "status": "sent",
            "channel": "email",
            "notification_id": notification.id,
        }

    def list_user_notifications(self, user_id: int, limit: int = 20, offset: int = 0) -> tuple[list[Notification], int]:
        return self.notifications.list_by_user(user_id, limit, offset)

    # Async method for Temporal activities (consolidated from workers/temporal/services/notification_service.py)
    async def send_confirmation(self, user_id: int, appointment_id: int) -> dict[str, str | int]:
        """Send confirmation notification (delivery boundary) for Temporal activities."""
        return await self.notifications.send_confirmation(user_id, appointment_id)
