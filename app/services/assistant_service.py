import asyncio
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models import User
from app.repositories.ai_interactions import AIInteractionRepository
from app.services.assistant_prompts import DISCLAIMER, PROMPT_NAV_V1, PROMPT_VERSION_NAV
from app.services.llm_provider import LLMProvider, get_llm_provider
from app.services.safety_service import SafetyCheck
from app.services.search_service import search_services


class AssistantService:
    def __init__(self, db: Session, provider: LLMProvider | None = None) -> None:
        self.db = db
        self.provider = provider or get_llm_provider()
        self.safety = SafetyCheck()
        self.interactions = AIInteractionRepository(db)

    async def stream_answer(self, question: str, user: User) -> AsyncIterator[dict]:
        decision = self.safety.classify(question)
        if decision.refused:
            answer = (
                "I can't provide medical advice. Please contact the appropriate clinic service"
                if not decision.acute else "I can't provide medical advice. Please contact urgent care or emergency services now"
            ) + f". {DISCLAIMER}"
            yield {"type": "token", "value": answer}
            self._persist(user.id, decision.intent, [], answer, True)
            return

        results = await search_services(self.db, question, settings.retrieval_top_k)
        if not results:
            answer = "We don't offer that."
            yield {"type": "token", "value": answer}
            self._persist(user.id, decision.intent, [], answer, False)
            return

        context = "\n---\n".join(
            f"[{item['department']}] {item['service_name']}. {item['content']}" for item in results
        )
        prompt = PROMPT_NAV_V1.format(clinic="SmartHealth", context=context, user_question=question)
        answer_parts: list[str] = []
        persisted = False
        try:
            async for token in self.provider.stream(prompt):
                answer_parts.append(token)
                yield {"type": "token", "value": token}
        except asyncio.CancelledError:
            self._persist(user.id, decision.intent, [item["service_id"] for item in results], "".join(answer_parts), False)
            persisted = True
            raise
        finally:
            if answer_parts and not persisted:
                self._persist(user.id, decision.intent, [item["service_id"] for item in results], "".join(answer_parts), False)

        yield {"type": "citations", "value": [
            {"service_id": item["service_id"], "service_name": item["service_name"], "department": item["department"]}
            for item in results
        ]}

    def _persist(self, user_id: int, intent: str, retrieved_ids: list[int], answer: str, refused: bool) -> None:
        self.interactions.create_interaction(
            user_id=user_id,
            intent=intent,
            retrieved_ids=retrieved_ids,
            answer=answer,
            model=settings.llm_model,
            prompt_version=PROMPT_VERSION_NAV,
            refused=refused,
        )
