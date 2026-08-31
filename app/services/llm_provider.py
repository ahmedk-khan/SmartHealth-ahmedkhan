from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.exceptions import ExternalServiceError
from app.core.settings import settings


class LLMProvider(ABC):
    @abstractmethod
    async def stream(self, prompt: str) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def complete_json(self, prompt: str) -> str:
        raise NotImplementedError


class FakeLLM(LLMProvider):
    """Deterministic provider for tests and local development."""

    def __init__(self, answer: str | None = None) -> None:
        self.answer = answer

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        answer = self.answer or "Based on the available clinic services, please choose the service that best matches your appointment needs."
        for token in answer.split():
            yield f"{token} "

    async def complete_json(self, prompt: str) -> str:
        return "{}"


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def _complete(self, prompt: str, stream: bool = False) -> Any:
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": stream},
                )
                response.raise_for_status()
                return response
        except httpx.HTTPError as exc:
            raise ExternalServiceError("LLM provider is temporarily unavailable", status_code=502, code="LLM_UNAVAILABLE") from exc

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        response = await self._complete(prompt, stream=False)
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExternalServiceError("LLM provider returned an invalid response", status_code=502, code="LLM_INVALID_RESPONSE") from exc
        for token in content.split():
            yield f"{token} "

    async def complete_json(self, prompt: str) -> str:
        response = await self._complete(prompt, stream=False)
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExternalServiceError("LLM provider returned an invalid response", status_code=502, code="LLM_INVALID_RESPONSE") from exc


def get_llm_provider() -> LLMProvider:
    if not settings.llm_api_key:
        return FakeLLM()
    return OpenAICompatibleLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
