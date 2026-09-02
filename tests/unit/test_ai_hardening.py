import asyncio
from types import SimpleNamespace

import pytest

from app.core.settings import Settings
from app.core.authorization.permissions import Permission, ROLE_PERMISSIONS
from app.services.safety_service import SafetyCheck
from app.services.assistant_service import AssistantService
from app.services.assistant_prompts import DISCLAIMER


def test_production_requires_llm_credentials():
    with pytest.raises(ValueError, match="LLM_API_KEY must be set"):
        Settings(
            app_env="production",
            jwt_secret="a" * 48,
            llm_provider="groq",
            llm_api_key="",
        )


def test_unknown_llm_provider_is_rejected():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        Settings(app_env="test", llm_provider="not-a-provider")


def test_ai_role_permissions_match_business_boundaries():
    from app.models import UserRole

    assert Permission.ANALYTICS_READ not in ROLE_PERMISSIONS[UserRole.patient]
    assert Permission.ANALYTICS_READ not in ROLE_PERMISSIONS[UserRole.provider]
    assert Permission.ANALYTICS_READ in ROLE_PERMISSIONS[UserRole.front_desk]
    assert Permission.ANALYTICS_READ in ROLE_PERMISSIONS[UserRole.admin]
    assert Permission.APPOINTMENT_CREATE in ROLE_PERMISSIONS[UserRole.patient]


def test_acute_heart_burning_is_provider_independent():
    decision = SafetyCheck().classify("my heart is burining what should i do")

    assert decision.refused is True
    assert decision.acute is True
    assert decision.intent == "acute_medical_advice"


def test_service_listing_is_exact_catalog_text():
    service = AssistantService.__new__(AssistantService)
    answer = service._format_service_listing([
        {"service_id": 1, "service_name": "Heart Checkup ", "department": "Cardiology"},
        {"service_id": 2, "service_name": "Heart Checkup", "department": "Cardiology"},
    ])

    assert answer == "Available services: Heart Checkup (Cardiology)."
    assert "Preparation" not in answer
    assert "Specialty" not in answer
    assert "**" not in answer


def test_specialist_navigation_uses_real_service_preparation(monkeypatch):
    service = AssistantService.__new__(AssistantService)
    service.services = SimpleNamespace(
        get_by_id=lambda service_id: SimpleNamespace(
            id=service_id,
            name="Orthopaedics Consultation",
            preparation_instructions="Bring prior imaging reports",
        )
    )
    monkeypatch.setattr(
        "app.services.assistant_service.search_services",
        lambda *args, **kwargs: asyncio.sleep(0, result=[
            {
                "service_id": 42,
                "service_name": "Orthopaedics Consultation",
                "department": "Orthopaedics",
            }
        ]),
    )

    answer, citations, retrieved_ids = asyncio.run(
        service._answer_specialist_navigation("Which specialist should I see for knee pain?")
    )

    assert "Orthopaedics Consultation" in answer
    assert "Bring prior imaging reports." in answer
    assert DISCLAIMER in answer
    assert citations == [{"service_id": 42, "service_name": "Orthopaedics Consultation", "department": "Orthopaedics"}]
    assert retrieved_ids == [42]
