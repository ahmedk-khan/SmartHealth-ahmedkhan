import asyncio

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
