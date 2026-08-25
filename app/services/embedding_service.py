import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.exceptions import AppError
from app.core.settings import settings


class EmbeddingProvider(ABC):
    """Provider contract for converting text into fixed-size vectors."""

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


def _parse_embedding_response(response: Any) -> list[list[float]]:
    if isinstance(response, list) and response and isinstance(response[0], (int, float)):
        return [response]
    if isinstance(response, list) and all(isinstance(item, list) for item in response):
        return response
    raise AppError(
        "Embedding provider returned an unsupported response",
        status_code=502,
        error_type="embedding_provider_error",
    )


def _configured_api_key() -> str:
    api_key = settings.embedding_api_key.strip()
    if not api_key or api_key.startswith("#") or "paste in" in api_key.lower():
        return ""
    return api_key


def _validate_embeddings(embeddings: list[list[float]], texts: list[str], dimensions: int) -> list[list[float]]:
    if len(embeddings) != len(texts) or any(len(item) != dimensions for item in embeddings):
        raise AppError(
            "Embedding provider returned vectors with unexpected dimensions",
            status_code=502,
            error_type="embedding_dimensions_invalid",
        )
    return embeddings


class FakeEmbeddings(EmbeddingProvider):
    """Deterministic local provider for tests and development without credentials."""

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or settings.embedding_dimensions

    def _embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            values[index] += 1.0 if digest[4] % 2 else -1.0
        magnitude = math.sqrt(sum(value * value for value in values))
        return [value / magnitude for value in values] if magnitude else values

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    """Production embedding provider backed by the Hugging Face inference API."""

    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"https://router.huggingface.co/hf-inference/models/{self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, headers=headers, json={"inputs": texts})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppError(
                "Embedding provider request failed",
                status_code=502,
                error_type="embedding_provider_unavailable",
                detail=str(exc),
            ) from exc
        return _validate_embeddings(_parse_embedding_response(response.json()), texts, self.dimensions)


def get_embedding_provider() -> EmbeddingProvider:
    api_key = _configured_api_key()
    if not api_key:
        return FakeEmbeddings()
    provider = settings.embedding_provider.split("#", 1)[0].strip().lower()
    if provider != "huggingface":
        raise AppError(
            f"Unsupported embedding provider: {settings.embedding_provider}",
            status_code=503,
            error_type="embedding_provider_not_configured",
        )
    return HuggingFaceEmbeddingProvider(api_key, settings.embedding_model, settings.embedding_dimensions)


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await get_embedding_provider().embed_documents(texts)