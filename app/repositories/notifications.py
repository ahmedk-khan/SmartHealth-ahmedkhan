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

    # Async notification delivery methods (consolidated from notification_repo.py)
    async def send_confirmation(self, user_id: int, appointment_id: int) -> dict[str, str | int]:
        """Send confirmation notification (delivery boundary)."""
        # TODO: persist an outbox row when confirmation delivery is wired.
        return {"user_id": user_id, "appointment_id": appointment_id, "status": "QUEUED"}


class NotificationDeliveryRepository:
    """Deprecated: Use NotificationRepository.send_confirmation() instead."""
    
    def __init__(self, session) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession
        self.session: AsyncSession = session

    async def send_confirmation(self, user_id: int, appointment_id: int) -> dict[str, str | int]:
        """Deprecated: Use NotificationRepository.send_confirmation() instead."""
        # TODO: persist an outbox row when confirmation delivery is wired.
        return {"user_id": user_id, "appointment_id": appointment_id, "status": "QUEUED"}

