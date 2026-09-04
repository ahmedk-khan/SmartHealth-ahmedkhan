import asyncio
import hashlib

import pytest

from app.core.exceptions import AppError
from app.services.embedding_service import (
    EmbeddingProvider,
    FakeEmbeddings,
    HuggingFaceEmbeddingProvider,
    get_embedding_provider,
)


def test_fake_embeddings_are_deterministic_and_dimensioned():
    provider = FakeEmbeddings(dimensions=8)

    first = asyncio.run(provider.embed_documents(["heart care", "heart care"]))
    second = asyncio.run(provider.embed_documents(["heart care"]))

    assert isinstance(provider, EmbeddingProvider)
    assert first[0] == first[1] == second[0]
    assert len(first[0]) == 8


def test_fake_embeddings_support_empty_input():
    assert asyncio.run(FakeEmbeddings().embed_documents([])) == []


def test_provider_factory_uses_fake_without_api_key(monkeypatch):
    from app.core.settings import settings

    monkeypatch.setattr(settings, "embedding_api_key", "")

    assert isinstance(get_embedding_provider(), FakeEmbeddings)


def test_provider_factory_rejects_unknown_configured_provider(monkeypatch):
    from app.core.settings import settings

    monkeypatch.setattr(settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(settings, "embedding_provider", "unknown")

    with pytest.raises(AppError, match="Unsupported embedding provider"):
        get_embedding_provider()


def test_provider_factory_builds_huggingface_provider(monkeypatch):
    from app.core.settings import settings

    monkeypatch.setattr(settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(settings, "embedding_provider", "huggingface")
    monkeypatch.setattr(settings, "embedding_model", "test-model")
    monkeypatch.setattr(settings, "embedding_dimensions", 8)

    provider = get_embedding_provider()

    assert isinstance(provider, HuggingFaceEmbeddingProvider)
    assert provider.model == "test-model"
    assert provider.dimensions == 8


def test_publish_embedding_activity_batches_chunks_in_order(monkeypatch):
    from app.core.settings import settings
    from app.workers.temporal.activities import service_publish

    calls = []

    async def fake_generate_embeddings(texts):
        calls.append(texts)
        return [[float(index)] for index in range(len(texts))]

    monkeypatch.setattr(settings, "embedding_batch_size", 2)
    monkeypatch.setattr("app.services.service_publish_service.generate_embeddings", fake_generate_embeddings)
    chunks = [{"chunk_index": index, "content": f"chunk-{index}"} for index in range(5)]

    result = asyncio.run(service_publish.embed_chunks(chunks))

    assert calls == [["chunk-0", "chunk-1"], ["chunk-2", "chunk-3"], ["chunk-4"]]
    assert [chunk["chunk_index"] for chunk in result] == list(range(5))
    assert [chunk["embedding"] for chunk in result] == [[0.0], [1.0], [0.0], [1.0], [0.0]]


def test_publish_embedding_activity_reuses_unchanged_chunk(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base
    from app.models import ContentChunk
    from app.services.embedding_service import embedding_model_id
    from app.workers.temporal.activities import service_publish

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    unchanged_content = "unchanged"
    unchanged_hash = hashlib.sha256(unchanged_content.encode("utf-8")).hexdigest()
    session.add(ContentChunk(
        service_id=7,
        content_hash=unchanged_hash,
        department="Cardiology",
        specialty="Cardiac",
        published=True,
        source_type="service",
        source_id=7,
        chunk_index=0,
        content=unchanged_content,
        token_count=1,
        embedding=[9.0] * 1024,
        embedding_model=embedding_model_id(),
    ))
    session.commit()

    calls = []

    async def fake_generate_embeddings(texts):
        calls.append(texts)
        return [[2.0] * 1024 for _ in texts]

    monkeypatch.setattr("app.workers.temporal.activity_session.db_module.SessionLocal", lambda: session)
    monkeypatch.setattr("app.services.service_publish_service.generate_embeddings", fake_generate_embeddings)
    result = asyncio.run(service_publish.embed_chunks([
        {"service_id": 7, "chunk_index": 0, "content": unchanged_content},
        {"service_id": 7, "chunk_index": 1, "content": "changed"},
    ]))

    assert calls == [["changed"]]
    assert list(result[0]["embedding"]) == [9.0] * 1024
    assert result[1]["embedding"] == [2.0] * 1024
    session.close()
    Base.metadata.drop_all(bind=engine)
