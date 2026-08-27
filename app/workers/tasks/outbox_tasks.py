import logging
import json
import datetime

from app.celery_app import celery_app
from app.db import SessionLocal
from app.integrations.kafka_client import KafkaEventPublisher, KafkaProducerError
from app.models import AnalyticsDaily, FailedJob, OutboxEvent


logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.outbox_tasks.publish_pending_events",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def publish_pending_events(self, limit: int = 100) -> dict[str, int]:
    db = SessionLocal()
    published = 0
    failed = 0
    try:
        events = db.query(OutboxEvent).filter(OutboxEvent.status == "PENDING").order_by(OutboxEvent.id).limit(limit).all()
        publisher = KafkaEventPublisher()
        for event in events:
            try:
                publisher.publish_event(
                    event_type=event.event_type,
                    entity_type=event.entity_type,
                    entity_id=event.entity_id,
                    **event.payload,
                )
                event.status = "PUBLISHED"
                event.published_at = datetime.datetime.now(datetime.timezone.utc)
                event.attempts += 1
                published += 1
            except KafkaProducerError as exc:
                event.attempts += 1
                event.last_error = str(exc)[:500]
                if event.attempts >= self.max_retries + 1:
                    event.status = "FAILED"
                    db.add(FailedJob(
                        task_name=self.name,
                        task_id=self.request.id,
                        exception_type=type(exc).__name__,
                        error_message=str(exc),
                        payload=json.dumps({"event_id": event.event_id, "event_type": event.event_type}),
                    ))
                    today = datetime.datetime.now(datetime.timezone.utc).date()
                    aggregate = db.query(AnalyticsDaily).filter(AnalyticsDaily.date == today).first()
                    if aggregate is None:
                        aggregate = AnalyticsDaily(date=today)
                        db.add(aggregate)
                    aggregate.failed_workflows += 1
                failed += 1
        db.commit()
        return {"published": published, "failed": failed}
    except Exception:
        db.rollback()
        logger.exception("Outbox publishing task failed")
        raise
    finally:
        db.close()