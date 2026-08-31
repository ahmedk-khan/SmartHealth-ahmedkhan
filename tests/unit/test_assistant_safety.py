import pytest

from app.core.exceptions import AppError
from app.services.safety_service import SafetyCheck


def test_safety_check_rejects_empty_and_gibberish_input():
    safety = SafetyCheck()

    with pytest.raises(AppError):
        safety.normalize("   ")

    with pytest.raises(AppError):
        safety.normalize("asdfghjklqwerty")


def test_safety_check_flags_medical_and_appointment_intents():
    safety = SafetyCheck()

    assert safety.classify("Diagnose me: I have knee pain").refused is True
    assert safety.classify("What is my appointment status?").intent == "appointment"
    assert safety.classify("What preparation do I need for the MRI?").intent == "preparation"
