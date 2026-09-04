import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import AppError
from app.services import assistant_graph as assistant_graph_module
from app.services.assistant_graph import AssistantGraph, AssistantState
from app.services.assistant_service import AssistantService
from app.services.communication_service import CommunicationService
from app.services.embedding_service import FakeEmbeddings, get_embedding_provider
from app.core.settings import settings


class MemoryAIStore:
    def __init__(self):
        self.values = {}

    async def get_cached_answer(self, question, *, user_scope, model_id, prompt_version):
        return self.values.get((question, user_scope, model_id, prompt_version))

    async def cache_answer(self, question, answer, citations, *, user_scope, model_id, prompt_version):
        self.values[(question, user_scope, model_id, prompt_version)] = {
            "answer": answer,
            "citations": citations,
        }


class RecordingProvider:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        yield "grounded answer"


class FailingProvider:
    async def stream(self, prompt):
        if False:
            yield ""
        raise RuntimeError("provider details must not reach clients")


def _user():
    return SimpleNamespace(id=7, role=SimpleNamespace(value="patient"))


def _service(provider, store):
    service = AssistantService.__new__(AssistantService)
    service.db = SimpleNamespace()
    service.provider = provider
    service.ai_store = store
    service.safety = __import__("app.services.safety_service", fromlist=["SafetyCheck"]).SafetyCheck()
    service.slots = SimpleNamespace(list_by_service=lambda *args, **kwargs: ([], 0))
    service._persist_interaction = AsyncMock()
    service._prior_retrieved_service_ids = AsyncMock(return_value=[])
    return service


def test_cache_write_and_read_use_same_role_aware_scope(monkeypatch):
    provider = RecordingProvider()
    store = MemoryAIStore()
    service = _service(provider, store)

    async def fake_search(*args):
        return [{
            "service_id": 1,
            "service_name": "Cardiology",
            "department": "Heart Care",
            "content": "Cardiology consultation",
        }]

    monkeypatch.setattr("app.services.assistant_service.search_services", fake_search)
    user = _user()

    async def run_once():
        return [event async for event in service.stream_answer("Where is cardiology?", user)]

    asyncio.run(run_once())
    asyncio.run(run_once())

    assert len(provider.prompts) == 1


def test_conversation_history_is_included_in_provider_prompt(monkeypatch):
    provider = RecordingProvider()
    service = _service(provider, MemoryAIStore())

    async def fake_search(*args):
        return [{
            "service_id": 1,
            "service_name": "Cardiology",
            "department": "Heart Care",
            "content": "Cardiology consultation",
        }]

    monkeypatch.setattr("app.services.assistant_service.search_services", fake_search)
    history = [
        {"role": "user", "content": "I need heart care."},
        {"role": "assistant", "content": "Cardiology may be relevant."},
    ]

    async def run():
        return [event async for event in service.stream_answer("Where is it?", _user(), conversation_history=history)]

    asyncio.run(run())

    assert "I need heart care." in provider.prompts[0]
    assert "Cardiology may be relevant." in provider.prompts[0]


def test_provider_failure_emits_safe_structured_ai_error(monkeypatch):
    service = _service(FailingProvider(), MemoryAIStore())

    async def fake_search(*args):
        return [{
            "service_id": 1,
            "service_name": "Cardiology",
            "department": "Heart Care",
            "content": "Cardiology consultation",
        }]

    monkeypatch.setattr("app.services.assistant_service.search_services", fake_search)

    async def run():
        return [event async for event in service.stream_answer("Where is cardiology?", _user())]

    events = asyncio.run(run())
    errors = [event for event in events if event["type"] == "error"]

    assert errors == [{
        "type": "error",
        "value": {
            "type": "ai_error",
            "message": "The AI assistant is temporarily unavailable. Please try again later.",
            "code": "AI_PIPELINE_UNAVAILABLE",
        },
    }]


def test_no_match_navigation_uses_provider_for_conversation(monkeypatch):
    provider = RecordingProvider()
    service = _service(provider, MemoryAIStore())

    async def no_results(*args):
        return []

    monkeypatch.setattr("app.services.assistant_service.search_services", no_results)

    async def run():
        return [event async for event in service.stream_answer("Hi, can you help me?", _user())]

    events = asyncio.run(run())
    answer = "".join(event["value"] for event in events if event["type"] == "text")

    assert provider.prompts
    assert "Hi, can you help me?" in provider.prompts[0]
    assert answer == "grounded answer"
    assert "we don't offer that" not in answer.lower()


def test_production_requires_embedding_api_key(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "embedding_api_key", "")

    with pytest.raises(AppError, match="EMBEDDING_API_KEY must be configured"):
        get_embedding_provider()


def test_local_embedding_fallback_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "embedding_api_key", "")

    with caplog.at_level("WARNING"):
        provider = get_embedding_provider()

    assert isinstance(provider, FakeEmbeddings)
    assert "FakeEmbeddings" in caplog.text


def test_communication_prompts_contain_real_appointment_values():
    service = CommunicationService.__new__(CommunicationService)
    summary_prompt = service._build_summary_prompt(
        {
            "provider_name": "Dr. Aisha Khan",
            "service_name": "Cardiology Consultation",
            "appointment_date": "September 2, 2026",
            "appointment_time": "14:00",
            "location": "Main Clinic",
            "service_description": "Heart health consultation",
        },
        True,
        True,
    )
    followup_prompt = service._build_followup_prompt(
        {
            "provider_name": "Dr. Aisha Khan",
            "service_name": "Cardiology Consultation",
            "patient_name": "Sam Lee",
            "appointment_date": "September 2, 2026",
            "visit_completed": True,
            "tone": "professional",
        },
        True,
    )

    assert "Dr. Aisha Khan" in summary_prompt
    assert "Main Clinic" in summary_prompt
    assert "[PROVIDER]" not in summary_prompt
    assert "Dr. Aisha Khan" in followup_prompt
    assert "Sam Lee" in followup_prompt
    assert "[PATIENT]" not in followup_prompt


def test_assistant_graph_awaits_retrieval_and_runs_async(monkeypatch):
    async def fake_search(*args):
        return [{"service_id": 9, "name": "Cardiology"}]

    monkeypatch.setattr(assistant_graph_module, "search_services", fake_search)
    graph = AssistantGraph(SimpleNamespace())

    result = asyncio.run(graph.run(AssistantState(question="Find cardiology", user_id=7)))

    assert isinstance(result, AssistantState)
    assert result.retrieved_ids == [9]
