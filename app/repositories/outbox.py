from app.models import AnalyticsDaily, FailedJob, OutboxEvent
from app.repositories.base import BaseRepository


class OutboxRepository(BaseRepository):
    def list_pending(self, limit: int) -> list[OutboxEvent]:
        """Return pending outbox events ordered by ID up to the requested limit."""
        return self.db.query(OutboxEvent).filter(OutboxEvent.status == "PENDING").order_by(OutboxEvent.id).limit(limit).all()

    def mark_published(self, event: OutboxEvent, published_at) -> None:
        """Mark an outbox event published and increment its attempt count."""
        event.status = "PUBLISHED"
        event.published_at = published_at
        event.attempts += 1

    def record_failed_event(self, event: OutboxEvent, task_name: str, task_id: str | None, error: Exception, max_attempts: int, payload: str, today) -> None:
        """Record an outbox failure and update the daily failed-workflow aggregate when exhausted."""
        event.attempts += 1
        event.last_error = str(error)[:500]
        if event.attempts >= max_attempts:
            event.status = "FAILED"
            self.db.add(FailedJob(
                task_name=task_name,
                task_id=task_id,
                exception_type=type(error).__name__,
                error_message=str(error),
                payload=payload,
            ))
            aggregate = self.db.query(AnalyticsDaily).filter(AnalyticsDaily.date == today).first()
            if aggregate is None:
                aggregate = AnalyticsDaily(date=today)
                self.db.add(aggregate)
            aggregate.failed_workflows += 1

