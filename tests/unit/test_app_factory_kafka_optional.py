import asyncio
from types import SimpleNamespace

from app.core import app_factory as app_factory_module


class StubConnection:
    def execute(self, *args, **kwargs):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class StubEngine:
    def connect(self):
        return StubConnection()

    def dispose(self):
        return None


def test_create_app_allows_kafka_unavailable(monkeypatch):
    monkeypatch.setattr(app_factory_module, "engine", StubEngine())
    monkeypatch.setattr(
        app_factory_module,
        "settings",
        SimpleNamespace(
            app_env="local",
            kafka_enabled=True,
            kafka_bootstrap_servers="kafka:29092",
            cors_allowed_origins=[],
            redis_url="redis://localhost:6379/0",
        ),
    )

    class FailingKafkaProducer:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("DNS failure")

    monkeypatch.setattr(app_factory_module, "KafkaProducer", FailingKafkaProducer)

    app = app_factory_module.create_app()

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run_lifespan())
