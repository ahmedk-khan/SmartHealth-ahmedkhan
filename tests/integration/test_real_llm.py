"""Opt-in smoke tests for the configured OpenAI-compatible LLM provider.

Run only with real credentials and an explicit opt-in:

    RUN_REAL_LLM_TESTS=1 pytest -m integration tests/integration/test_real_llm.py -q

The tests never read or print the credential value.
"""

import asyncio
import os

import pytest

from app.core.settings import settings
from app.services.llm_provider import FakeLLM, get_llm_provider
from app.services.safety_service import SafetyCheck


pytestmark = pytest.mark.integration


def _require_real_llm() -> None:
    if os.getenv("RUN_REAL_LLM_TESTS") != "1":
        pytest.skip("Set RUN_REAL_LLM_TESTS=1 to call the configured LLM provider")
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY is not configured")


def test_real_provider_returns_a_completion():
    _require_real_llm()
    provider = get_llm_provider()
    assert not isinstance(provider, FakeLLM)

    answer = asyncio.run(provider.complete(
        "Reply with exactly one short sentence confirming that you are online."
    ))

    assert isinstance(answer, str)
    assert answer.strip()


def test_real_provider_streams_progressively():
    _require_real_llm()
    provider = get_llm_provider()

    async def collect():
        chunks = []
        async for chunk in provider.stream(
            "Reply in five words confirming that streaming works."
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert len(chunks) > 1
    assert "".join(chunks).strip()


def test_medical_refusal_does_not_require_a_real_provider():
    decision = SafetyCheck().classify("my heart is burining what should i do")

    assert decision.refused is True
    assert decision.acute is True
