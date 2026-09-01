"""Fake LLM implementation for isolated testing without external dependencies."""

from typing import Any, AsyncGenerator


class FakeLLM:
    """
    A deterministic, network-free LLM mock for testing assistant layer.
    
    Provides predictable responses for different query patterns:
    - Navigation questions: return canned answers with citations
    - Appointment questions: return appointment status info
    - Preparation questions: return preparation guidance
    - Refused questions: return safety refusal message
    - Malformed: raise validation errors
    """
    
    def __init__(self, model_name: str = "fake-gpt-4"):
        self.model_name = model_name
        self.call_count = 0
        self.last_prompt = None
    
    async def create_message_stream(
        self, 
        messages: list[dict[str, str]], 
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Stream a fake response based on the last user message.
        
        Returns an async generator yielding token-like chunks.
        """
        self.call_count += 1
        
        # Extract the last user message
        user_message = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            ""
        )
        self.last_prompt = user_message
        
        # Validate basic message structure
        if not user_message or len(user_message.strip()) < 2:
            raise ValueError("Question must be at least 2 characters")
        
        if len(user_message) > 2000:
            raise ValueError("Question must not exceed 2000 characters")
        
        normalized = user_message.lower()
        
        # Route to different response types
        if any(word in normalized for word in ["diagnose", "medication", "treatment", "symptom", "disease"]):
            response_tokens = self._medical_advice_response()
        elif any(word in normalized for word in ["appointment", "booking", "schedule", "visit"]):
            response_tokens = self._appointment_response()
        elif any(word in normalized for word in ["prepare", "preparation", "fasting", "medication", "bring"]):
            response_tokens = self._preparation_response()
        elif any(word in normalized for word in ["available", "open", "time", "slot", "when"]):
            response_tokens = self._availability_response()
        else:
            response_tokens = self._navigation_response()
        
        # Yield tokens one by one
        for token in response_tokens:
            yield {
                "choices": [
                    {
                        "delta": {"content": token},
                        "finish_reason": None,
                    }
                ]
            }
        
        # Yield final chunk with finish_reason
        yield {
            "choices": [
                {
                    "delta": {"content": ""},
                    "finish_reason": "stop",
                }
            ]
        }
    
    def _medical_advice_response(self) -> list[str]:
        """Response for medical/diagnosis questions."""
        response = (
            "I can't provide medical advice. "
            "Please consult a qualified healthcare provider. "
            "This is not medical advice and should not be used for diagnosis or treatment decisions."
        )
        return [response[i:i+10] for i in range(0, len(response), 10)]
    
    def _appointment_response(self) -> list[str]:
        """Response for appointment-related questions."""
        response = (
            "Your upcoming appointment with Dr. Johnson for cardiology is scheduled for "
            "Tuesday, August 15, 2026 at 2:00 PM at the Main Clinic. "
            "Please arrive 15 minutes early and bring your insurance card."
        )
        return self._tokenize(response)
    
    def _preparation_response(self) -> list[str]:
        """Response for preparation/guidance questions."""
        response = (
            "For your MRI scan, please: 1) Remove all metal objects, 2) Inform staff of any implants, "
            "3) Wear comfortable clothing, 4) Avoid caffeine for 2 hours before, "
            "5) Bring your insurance card and photo ID. The scan takes about 30 minutes."
        )
        return self._tokenize(response)
    
    def _availability_response(self) -> list[str]:
        """Response for availability questions."""
        response = (
            "We have available appointments for General Consultation next week: "
            "Monday 10:00 AM, Tuesday 2:00 PM, Thursday 9:30 AM, and Friday 3:00 PM. "
            "Please note: Cardiology has limited availability; next opening is August 20."
        )
        return self._tokenize(response)
    
    def _navigation_response(self) -> list[str]:
        """Default navigation/service catalog response."""
        response = (
            "We offer comprehensive healthcare services including cardiology, orthopedics, dermatology, "
            "and general medicine. Our Board-certified providers use the latest diagnostic equipment. "
            "To schedule an appointment, visit our booking portal or call our scheduling team."
        )
        return self._tokenize(response)
    
    @staticmethod
    def _tokenize(text: str, chunk_size: int = 15) -> list[str]:
        """Split text into token-like chunks."""
        tokens = []
        for i in range(0, len(text), chunk_size):
            tokens.append(text[i:i+chunk_size])
        return tokens if tokens else [""]


class FakeLLMContainer:
    """
    Injectable container for FakeLLM to be used in tests.
    Mimics the interface of the real LLM provider.
    """
    
    def __init__(self, fake_llm: FakeLLM | None = None):
        self.llm = fake_llm or FakeLLM()
    
    async def create_message(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Non-streaming completion (for completeness)."""
        # Collect all streamed tokens
        full_response = ""
        async for chunk in self.llm.create_message_stream(
            messages, temperature, max_tokens
        ):
            content = chunk["choices"][0]["delta"].get("content", "")
            if content:
                full_response += content
        
        return {
            "choices": [
                {
                    "message": {
                        "content": full_response,
                        "role": "assistant",
                    },
                    "finish_reason": "stop",
                }
            ]
        }

