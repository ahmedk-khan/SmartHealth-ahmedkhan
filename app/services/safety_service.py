import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyDecision:
    intent: str
    refused: bool
    acute: bool = False


class SafetyCheck:
    """Conservative, deterministic gate that runs before embeddings or retrieval."""

    _medical = re.compile(r"\b(diagnos|cause|caused|symptom|treat|treatment|medication|medicine|prescri|dose|dosage|what do i have)\w*\b", re.I)
    _acute = re.compile(r"\b(chest pain|difficulty breathing|can't breathe|cannot breathe|stroke|unconscious|severe bleeding|overdose|suicid)\w*\b", re.I)
    _preparation = re.compile(r"\b(prepare|preparation|bring|fast|fasting|arrive|metal)\w*\b", re.I)

    def classify(self, question: str) -> SafetyDecision:
        acute = bool(self._acute.search(question))
        if self._medical.search(question) or acute:
            return SafetyDecision("acute_medical_advice" if acute else "medical_advice", True, acute)
        return SafetyDecision("preparation" if self._preparation.search(question) else "navigation", False)
