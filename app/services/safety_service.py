import re
from dataclasses import dataclass

from app.core.exceptions import validation_error


@dataclass(frozen=True)
class SafetyDecision:
    intent: str
    refused: bool
    acute: bool = False


class SafetyCheck:
    """Conservative, deterministic gate that runs before embeddings or retrieval."""

    _medical = re.compile(r"\b(diagnos|cause|caused|symptom|treat|treatment|medication|medicine|prescri|dose|dosage|what do i have|what's wrong with me|prescribe)\w*\b", re.I)
    _acute = re.compile(r"\b(chest pain|difficulty breathing|can't breathe|cannot breathe|stroke|unconscious|severe bleeding|overdose|suicid)\w*\b", re.I)
    _preparation = re.compile(r"\b(prepare|preparation|bring|fast|fasting|arrive|metal|instructions)\w*\b", re.I)
    _availability = re.compile(r"\b(available|availability|open slot|open slots|when can i|book|appointment|appointments|schedule)\w*\b", re.I)
    _appointment = re.compile(r"\b(my appointment|my appointments|reschedule my|cancel my|when is my|check my appointment|appointment status)\b", re.I)
    _gibberish = re.compile(r"^(?:[bcdfghjklmnpqrstvwxyz]{6,}|[a-z]{1,2}\d{3,}|(?:\W|_)+)$", re.I)

    def normalize(self, question: str) -> str:
        normalized = " ".join(question.split())
        if not normalized:
            raise validation_error("Question cannot be empty")
        if len(normalized) > 2000:
            raise validation_error("Question is too long")
        if self._looks_gibberish(normalized):
            raise validation_error("Question looks invalid")
        return normalized

    def _looks_gibberish(self, question: str) -> bool:
        compact = re.sub(r"\s+", "", question)
        if not compact:
            return True
        alpha_count = sum(1 for char in compact if char.isalpha())
        if alpha_count < 3:
            return True
        vowel_count = sum(1 for char in compact.lower() if char in "aeiou")
        if alpha_count >= 6 and vowel_count == 0:
            return True
        if len(compact) >= 12 and len(set(compact.lower())) <= 3:
            return True
        if self._gibberish.match(question):
            return True
        alnum_count = sum(1 for char in compact if char.isalnum())
        if alnum_count and (alpha_count / alnum_count) < 0.3:
            return True
        return False

    def classify(self, question: str) -> SafetyDecision:
        acute = bool(self._acute.search(question))
        if self._medical.search(question) or acute:
            return SafetyDecision("acute_medical_advice" if acute else "medical_advice", True, acute)
        if self._appointment.search(question):
            return SafetyDecision("appointment", False)
        if self._availability.search(question):
            return SafetyDecision("availability", False)
        return SafetyDecision("preparation" if self._preparation.search(question) else "navigation", False)
