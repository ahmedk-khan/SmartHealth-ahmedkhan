import asyncio

import pytest

from app.workers.kafka.producer import EventPublisher


class DummyFuture:
    partition = 0

    def get(self, timeout=None):
        return None


class DummyProducer:
    def send(self, topic, key=None, value=None):
        return DummyFuture()


class DummyClient:
    def get_producer(self):
        return DummyProducer()


def test_publish_event_sync_contract_returns_event_payload(monkeypatch):
    publisher = EventPublisher(client=DummyClient())
    monkeypatch.setattr(publisher, "_enabled", True, raising=False)

    result = publisher.publish_event(
        event_type="service.published",
        entity_type="service",
        entity_id=42,
        department_id=7,
        status="published",
    )

    assert result["event_type"] == "service.published"
    assert result["entity_type"] == "service"
    assert result["entity_id"] == 42
    assert result["department_id"] == 7
    assert result["status"] == "published"
    assert "event_id" in result


def test_publish_event_rejects_running_event_loop(monkeypatch):
    publisher = EventPublisher(client=DummyClient())
    monkeypatch.setattr(publisher, "_enabled", True, raising=False)

    async def _run():
        with pytest.raises(RuntimeError, match="publish_event_async"):
            publisher.publish_event(
                event_type="service.published",
                entity_type="service",
                entity_id=99,
                status="published",
            )

    asyncio.run(_run())
