import datetime

from app.models import Notification, NotificationStatus
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository):
    def get_reminder(self, appointment_id: int) -> Notification | None:
        return self.db.query(Notification).filter(
            Notification.type == "APPOINTMENT_REMINDER",
            Notification.payload["appointment_id"].as_integer() == appointment_id,
        ).first()

    def get_follow_up(self, appointment_id: int) -> Notification | None:
        return self.db.query(Notification).filter(
            Notification.type == "VISIT_FOLLOW_UP",
            Notification.payload["appointment_id"].as_integer() == appointment_id,
        ).first()

    def list_by_user(self, user_id: int, limit: int = 20, offset: int = 0) -> tuple[list[Notification], int]:
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        total = query.count()
        items = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

    def get_by_id_for_update(self, notification_id: int) -> Notification | None:
        return self.db.query(Notification).filter(Notification.id == notification_id).with_for_update().one_or_none()

    def add_and_refresh(self, notification: Notification) -> Notification:
        self.add(notification)
        self.commit()
        self.refresh(notification)
        return notification

    def cancel(self, notification: Notification) -> Notification:
        notification.status = NotificationStatus.CANCELLED
        notification.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.commit()
        return notification

    def mark_sent(self, notification: Notification) -> None:
        notification.status = NotificationStatus.SENT
        self.commit()
