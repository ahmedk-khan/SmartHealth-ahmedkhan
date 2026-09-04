import os
import uuid

import pytest


pytestmark = pytest.mark.integration

_INTEGRATION_DEFAULTS = {
    "DATABASE_URL": "postgresql+psycopg://appuser:apppassword@localhost:5432/appdb",
    "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
    "TEMPORAL_HOST": "localhost:7233",
}


def _require_docker_integration() -> None:
    if os.getenv("RUN_DOCKER_INTEGRATION") != "1":
        pytest.skip("Set RUN_DOCKER_INTEGRATION=1 with docker compose services running")


def _integration_setting(name: str) -> str:
    value = os.getenv(name, _INTEGRATION_DEFAULTS[name])
    if name == "DATABASE_URL" and value.startswith("sqlite"):
        value = _INTEGRATION_DEFAULTS[name]
    if os.getenv("RUN_DOCKER_INTEGRATION_IN_CONTAINER") != "1":
        value = value.replace("@postgres:", "@localhost:").replace("kafka:29092", "localhost:9092").replace("kafka:9092", "localhost:9092").replace("temporal:7233", "localhost:7233")
    return value


def test_postgres_is_reachable():
    _require_docker_integration()
    import psycopg

    database_url = _integration_setting("DATABASE_URL").replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(database_url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)


def test_kafka_publish_and_consume_round_trip():
    _require_docker_integration()
    from kafka import KafkaConsumer, KafkaProducer

    topic = f"smarthealth.integration.{uuid.uuid4().hex}"
    bootstrap_servers = _integration_setting("KAFKA_BOOTSTRAP_SERVERS")
    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda value: value.encode(),
        request_timeout_ms=5000,
        max_block_ms=5000,
    )
    producer.send(topic, value="integration-event").get(timeout=10)
    producer.flush()
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        auto_offset_reset="earliest",
        consumer_timeout_ms=10000,
        group_id=f"smarthealth-test-{uuid.uuid4().hex}",
    )
    try:
        message = next(iter(consumer))
        assert message.value == b"integration-event"
    finally:
        consumer.close()
        producer.close()


def test_temporal_is_reachable():
    _require_docker_integration()
    from temporalio.client import Client

    import asyncio

    async def connect() -> None:
        client = await Client.connect(_integration_setting("TEMPORAL_HOST"))
        assert client.service_client is not None

    asyncio.run(connect())


def test_celery_worker_responds():
    _require_docker_integration()
    from app.workers.celery_app import celery_app

    result = celery_app.control.inspect(timeout=5).ping()
    assert result
