from types import SimpleNamespace

import pytest

from app.models.user import UserRole
from app.core.exceptions import AppError
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

    def test_staff_and_patient_scoping_uses_enum_roles(self):
        service = CommunicationService.__new__(CommunicationService)

        admin = SimpleNamespace(role=UserRole.admin)
        front_desk = SimpleNamespace(role=UserRole.front_desk)
        provider = SimpleNamespace(role=UserRole.provider)
        patient = SimpleNamespace(role=UserRole.patient, patient=SimpleNamespace(id=7))

        appointment = SimpleNamespace(patient_id=7)

        assert service._user_can_access_appointment(admin, appointment) is True
        assert service._user_can_access_appointment(front_desk, appointment) is True
        assert service._user_can_access_appointment(provider, appointment) is True
        assert service._user_can_access_appointment(patient, appointment) is True

        other_patient = SimpleNamespace(role=UserRole.patient, patient=SimpleNamespace(id=99))
        assert service._user_can_access_appointment(other_patient, appointment) is False

        assert service._user_is_staff(admin) is True
        assert service._user_is_staff(front_desk) is True
        assert service._user_is_staff(provider) is True
        assert service._user_is_staff(patient) is False

        assert service._user_is_admin(admin) is True
        assert service._user_is_admin(front_desk) is False
