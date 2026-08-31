import logging
import json
import datetime

from app.workers.celery_app import celery_app
from app.db import SessionLocal
from app.integrations.kafka_client import KafkaEventPublisher, KafkaProducerError
from app.models import OutboxEvent
from app.repositories import OutboxRepository


logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.celery.outbox.publish_pending_events",
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
        repository = OutboxRepository(db)
        events = repository.list_pending(limit)
        publisher = KafkaEventPublisher()
        for event in events:
            try:
                publisher.publish_event(
                    event_type=event.event_type,
                    entity_type=event.entity_type,
                    entity_id=event.entity_id,
                    **event.payload,
                )
                repository.mark_published(event, datetime.datetime.now(datetime.timezone.utc))
                published += 1
            except KafkaProducerError as exc:
                repository.record_failed_event(
                    event,
                    self.name,
                    self.request.id,
                    exc,
                    self.max_retries + 1,
                    json.dumps({"event_id": event.event_id, "event_type": event.event_type}),
                    datetime.datetime.now(datetime.timezone.utc).date(),
                )
                failed += 1
        repository.commit()
        return {"published": published, "failed": failed}
    except Exception:
        OutboxRepository(db).rollback()
        logger.exception("Outbox publishing task failed")
        raise
    finally:
        db.close()
