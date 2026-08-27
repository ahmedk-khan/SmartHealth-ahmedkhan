from app.core.exceptions import AppError
import datetime

from app.models import Appointment, Notification, NotificationStatus
from app.services.base import BaseService


class NotificationService(BaseService):
    def create_follow_up(self, appointment: Appointment) -> Notification:
        notification = Notification(
            user_id=appointment.patient.user_id,
            type="VISIT_FOLLOW_UP",
            payload={"appointment_id": appointment.id, "channel": "email"},
            status=NotificationStatus.PENDING,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def schedule_appointment_reminder(self, appointment_id: int) -> Notification:
        existing = self.db.query(Notification).filter(
            Notification.type == "APPOINTMENT_REMINDER",
            Notification.payload["appointment_id"].as_integer() == appointment_id,
        ).first()
        if existing:
            return existing
        appointment = self.db.query(Appointment).filter(Appointment.id == appointment_id).one_or_none()
        if appointment is None:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")
        notification = Notification(
            user_id=appointment.patient.user_id,
            type="APPOINTMENT_REMINDER",
            payload={"appointment_id": appointment.id, "channel": "email"},
            status=NotificationStatus.PENDING,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def cancel_notification(self, notification_id: int) -> Notification | None:
        notification = self.db.query(Notification).filter(Notification.id == notification_id).with_for_update().one_or_none()
        if notification is None or notification.status == NotificationStatus.CANCELLED:
            return notification
        if notification.status == NotificationStatus.SENT:
            return notification
        notification.status = NotificationStatus.CANCELLED
        notification.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        return notification

    def send_appointment_reminder(self, appointment_id: int) -> dict[str, object]:
        appointment = self.db.query(Appointment).filter(Appointment.id == appointment_id).one_or_none()
        if appointment is None:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")

        notification = self.schedule_appointment_reminder(appointment_id)
        if notification.status == NotificationStatus.CANCELLED:
            return {"appointment_id": appointment.id, "status": "cancelled", "notification_id": notification.id}
        notification.status = NotificationStatus.SENT
        self.db.commit()
        return {
            "appointment_id": appointment.id,
            "patient_id": appointment.patient_id,
            "provider_id": appointment.provider_id,
            "status": "sent",
            "channel": "email",
            "notification_id": notification.id,
        }
