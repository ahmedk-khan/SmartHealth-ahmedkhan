import asyncio
import logging
import pytest

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
import httpx

from app.core.exceptions import AppError
from app.services.search_service import search_services
from app.services.embedding_service import HuggingFaceEmbeddingProvider


def test_health_readiness_hides_raw_exception_class_names(monkeypatch, caplog):
    from app.main import app
    from app.api.v1.endpoints import health

    def failing_db_check(self):
        raise ConnectionError("Raw DB connection details should not leak")

    monkeypatch.setattr(health.HealthRepository, "check_database_connection", failing_db_check)

    with caplog.at_level(logging.ERROR):
        client = TestClient(app)
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"] == "error: Service temporarily unavailable"
    assert "ConnectionError" not in response.text
    assert "Raw DB connection details" not in response.text

    # Check server-side log contains full exception
    assert "Database readiness check failed" in caplog.text


def test_search_service_sanitizes_sqlalchemy_error(monkeypatch, caplog):
    class DummyRepo:
        def __init__(self, db):
            pass

        def search_candidates(self, query_embedding, limit):
            raise SQLAlchemyError("Sensitive SQL query details leaked")

    from app.services import search_service

    monkeypatch.setattr(search_service, "ContentChunkRepository", DummyRepo)
    monkeypatch.setattr(search_service, "generate_embeddings", lambda texts: asyncio.sleep(0, result=[[1.0] * 1024]))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(AppError) as exc_info:
            asyncio.run(search_services(None, "query", 5))

    err = exc_info.value
    assert err.status_code == 503
    assert err.error_type == "search_unavailable"
    assert err.message == "Service search is temporarily unavailable"
    assert err.detail is None
    assert "Sensitive SQL query details" in caplog.text


def test_embedding_service_sanitizes_httpx_error(caplog):
    provider = HuggingFaceEmbeddingProvider(api_key="secret-key", model="test-model", dimensions=1024)

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("Failed to connect to external HF host https://private.internal.host")

    httpx_client_backup = httpx.AsyncClient
    httpx.AsyncClient = DummyClient
    try:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(AppError) as exc_info:
                asyncio.run(provider.embed_documents(["test text"]))
    finally:
        httpx.AsyncClient = httpx_client_backup

    err = exc_info.value
    assert err.status_code == 502
    assert err.error_type == "embedding_provider_unavailable"
    assert err.message == "Embedding provider request failed"
    assert err.detail is None
    assert "Failed to connect to external HF host" in caplog.text
