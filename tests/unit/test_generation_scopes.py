from types import SimpleNamespace

import pytest

from app.models.user import UserRole
from app.core.exceptions import AppError, ForbiddenError
from app.core.authorization.policies import AppointmentOwnershipGuard
from app.core.authorization.service import ensure_admin_or_front_desk
from app.services.communication_service import CommunicationService


class TestCommunicationServiceAccess:
    def test_external_prompts_do_not_contain_appointment_phi(self):
        service = CommunicationService.__new__(CommunicationService)
        prompt = service._build_followup_prompt(
            {
                "provider_name": "[PROVIDER]",
                "service_name": "[SERVICE]",
                "patient_name": "[PATIENT]",
                "appointment_date": "[APPOINTMENT_DATE]",
                "visit_completed": True,
                "tone": "professional",
            },
            True,
        )

        assert "John Smith" not in prompt
        assert "2026-08-01" not in prompt
        assert "[PATIENT]" in prompt

    def test_generated_text_validation_rejects_unsafe_or_oversized_output(self):
        service = CommunicationService.__new__(CommunicationService)

        with pytest.raises(AppError):
            service._validate_generated_text("You should take this medication dosage.")
        with pytest.raises(AppError):
            service._validate_generated_text("x" * 4001)

    def test_prompt_tokens_can_be_restored_after_provider_call(self):
        service = CommunicationService.__new__(CommunicationService)

        restored = service._restore_prompt_tokens(
            "Hello [PATIENT], your appointment is with [PROVIDER].",
            {"[PATIENT]": "Alex", "[PROVIDER]": "Dr. Smith"},
        )

        assert restored == "Hello Alex, your appointment is with Dr. Smith."

    def test_appointment_access_uses_centralized_guards(self):
        admin = SimpleNamespace(role=UserRole.admin)
        front_desk = SimpleNamespace(role=UserRole.front_desk)
        provider = SimpleNamespace(role=UserRole.provider, provider=SimpleNamespace(id=3, user_id=30))
        patient = SimpleNamespace(role=UserRole.patient, patient=SimpleNamespace(id=7, user_id=70))
        other_patient = SimpleNamespace(role=UserRole.patient, patient=SimpleNamespace(id=99, user_id=99))

        appointment = SimpleNamespace(patient_id=7, provider_id=3, patient=patient.patient, provider=provider.provider)

        assert AppointmentOwnershipGuard(admin, appointment).passed() is True
        assert AppointmentOwnershipGuard(front_desk, appointment).passed() is True
        assert AppointmentOwnershipGuard(provider, appointment).passed() is True
        assert AppointmentOwnershipGuard(patient, appointment).passed() is True
        assert AppointmentOwnershipGuard(other_patient, appointment).passed() is False

        ensure_admin_or_front_desk(admin)
        ensure_admin_or_front_desk(front_desk)
        with pytest.raises(ForbiddenError):
            ensure_admin_or_front_desk(provider)
