import pytest

from app.core.exceptions import AppError
from app.services.safety_service import SafetyCheck


def test_safety_check_rejects_empty_and_gibberish_input():
    safety = SafetyCheck()

    with pytest.raises(AppError):
        safety.normalize("   ")

    with pytest.raises(AppError):
        safety.normalize("asdfghjklqwerty")

    assert safety.normalize("hi") == "hi"


def test_safety_check_flags_medical_and_appointment_intents():
    safety = SafetyCheck()

    assert safety.classify("Diagnose me: I have knee pain").refused is True
    heart_pain = safety.classify("My heart is feeling pain")
    assert heart_pain.refused is True
    assert heart_pain.acute is True
    heart_burning = safety.classify("my heart is burining what should i do")
    assert heart_burning.refused is True
    assert heart_burning.acute is True
    specialist = safety.classify("Which specialist should I see for knee pain?")
    assert specialist.refused is False
    assert specialist.intent == "specialist_navigation"
    assert safety.classify("What is my appointment status?").intent == "appointment"
    assert safety.classify("Do you know what slots I have booked?").intent == "appointment"
    assert safety.classify("How can I book?").intent == "booking"
    assert safety.classify("List down the slots you have available").intent == "availability"
    assert safety.classify("What preparation do I need for the MRI?").intent == "preparation"
