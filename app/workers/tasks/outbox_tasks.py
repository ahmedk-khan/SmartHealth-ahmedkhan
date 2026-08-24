import logging

from app.celery_app import celery_app
from app.db import SessionLocal
from app.integrations.kafka_client import KafkaEventPublisher, KafkaProducerError
from app.models import OutboxEvent


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
                event.attempts += 1
                published += 1
            except KafkaProducerError as exc:
                event.attempts += 1
                event.last_error = str(exc)[:500]
                failed += 1
        db.commit()
        return {"published": published, "failed": failed}
    except Exception:
        db.rollback()
        logger.exception("Outbox publishing task failed")
        raise
    finally:
        db.close()