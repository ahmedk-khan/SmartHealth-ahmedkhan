import hashlib
import math
import re
from typing import Any

import httpx

from app.core.exceptions import AppError
from app.core.settings import settings


def _fallback_embedding(text: str) -> list[float]:
    """Create a stable local embedding for development without an API key."""
    values = [0.0] * settings.embedding_dimensions
    for token in re.findall(r"\w+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % settings.embedding_dimensions
        values[index] += 1.0 if digest[4] % 2 else -1.0
    magnitude = math.sqrt(sum(value * value for value in values))
    return [value / magnitude for value in values] if magnitude else values


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


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    api_key = _configured_api_key()
    if not api_key:
        return [_fallback_embedding(text) for text in texts]
    provider = settings.embedding_provider.split("#", 1)[0].strip().lower()
    if provider != "huggingface":
        raise AppError(
            f"Unsupported embedding provider: {settings.embedding_provider}",
            status_code=503,
            error_type="embedding_provider_not_configured",
        )

    url = f"https://router.huggingface.co/hf-inference/models/{settings.embedding_model}"
    headers = {"Authorization": f"Bearer {api_key}"}
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
    embeddings = _parse_embedding_response(response.json())
    if len(embeddings) != len(texts) or any(len(item) != settings.embedding_dimensions for item in embeddings):
        raise AppError(
            "Embedding provider returned vectors with unexpected dimensions",
            status_code=502,
            error_type="embedding_dimensions_invalid",
        )
    return embeddings