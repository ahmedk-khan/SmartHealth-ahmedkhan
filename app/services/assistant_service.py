import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import timezone

from sqlalchemy.orm import Session

from app.core.authorization import Permission, authorize
from app.core.settings import settings
from app.models import User
from app.repositories import AIInteractionRepository, AppointmentRepository, PatientRepository, ProviderRepository, ServiceRepository, SlotRepository
from app.services.assistant_prompts import DISCLAIMER, PROMPT_NAV_V1, PROMPT_VERSION_ASSISTANT, PROMPT_VERSION_REPORT
from app.services.llm_provider import LLMProvider, get_llm_provider
from app.services.safety_service import SafetyCheck
from app.services.search_service import search_services
from app.services.utilisation_service import UtilisationService


logger = logging.getLogger(__name__)


class AssistantService:
    def __init__(self, db: Session, provider: LLMProvider | None = None) -> None:
        self.db = db
        self.provider = provider or get_llm_provider()
        self.safety = SafetyCheck()
        self.appointments = AppointmentRepository(db)
        self.patients = PatientRepository(db)
        self.providers = ProviderRepository(db)
        self.services = ServiceRepository(db)
        self.slots = SlotRepository(db)

    async def stream_answer(self, question: str, user: User) -> AsyncIterator[dict]:
        normalized = self.safety.normalize(question)
        decision = self.safety.classify(normalized)
        started_at = time.perf_counter()
        answer_parts: list[str] = []
        citations: list[dict[str, object]] = []
        refused = False
        retrieved_ids: list[int] = []
        model_name = settings.llm_model
        token_source = " ".join(normalized.split())

        try:
            if decision.refused:
                answer = self._refusal_message(decision.acute)
                refused = True
                answer_parts = [answer]
                yield {"type": "token", "value": answer}
            elif decision.intent == "appointment":
                answer, citations, retrieved_ids = await self._answer_own_appointments(normalized, user)
                for token in self._tokenize(answer):
                    answer_parts.append(token)
                    yield {"type": "token", "value": token}
            elif decision.intent == "preparation":
                answer, citations, retrieved_ids = await self._answer_preparation(normalized)
                for token in self._tokenize(answer):
                    answer_parts.append(token)
                    yield {"type": "token", "value": token}
            elif decision.intent == "availability":
                answer, citations, retrieved_ids = await self._answer_availability(normalized)
                for token in self._tokenize(answer):
                    answer_parts.append(token)
                    yield {"type": "token", "value": token}
            else:
                answer, citations, retrieved_ids = await self._answer_navigation(normalized)
                for token in self._tokenize(answer):
                    answer_parts.append(token)
                    yield {"type": "token", "value": token}

            yield {"type": "citations", "value": citations}
        except asyncio.CancelledError:
            await self._persist_interaction(
                user_id=user.id,
                question=normalized,
                intent=decision.intent,
                retrieved_ids=retrieved_ids,
                answer="".join(answer_parts).strip(),
                model_name=model_name,
                refused=refused,
                started_at=started_at,
                prompt_version=PROMPT_VERSION_ASSISTANT,
                input_tokens=self._estimate_tokens(token_source),
                output_tokens=self._estimate_tokens("".join(answer_parts)),
            )
            logger.info("Assistant stream truncated by client disconnect", extra={"user_id": user.id, "intent": decision.intent})
            raise
        else:
            await self._persist_interaction(
                user_id=user.id,
                question=normalized,
                intent=decision.intent,
                retrieved_ids=retrieved_ids,
                answer="".join(answer_parts).strip(),
                model_name=model_name,
                refused=refused,
                started_at=started_at,
                prompt_version=PROMPT_VERSION_ASSISTANT,
                input_tokens=self._estimate_tokens(token_source),
                output_tokens=self._estimate_tokens("".join(answer_parts)),
            )

    async def stream_report(self, period_start: str, period_end: str, user: User) -> AsyncIterator[dict]:
        authorize(user, Permission.ANALYTICS_READ)
        util_service = UtilisationService(self.db, self.provider)
        started_at = time.perf_counter()
        tokens: list[str] = []
        citations = [
            {
                "source": "analytics_daily",
                "period_start": period_start,
                "period_end": period_end,
            }
        ]
        completed = False
        try:
            raw_report = await util_service.generate(period_start, period_end)
            report_json = json.dumps(raw_report.model_dump(mode="json"), sort_keys=True)
            for token in self._tokenize(report_json):
                tokens.append(token)
                yield {"type": "token", "value": token}
            yield {"type": "report", "value": raw_report.model_dump(mode="json")}
            yield {"type": "citations", "value": citations}
            completed = True
        except asyncio.CancelledError:
            logger.info("Assistant report stream truncated by client disconnect", extra={"user_id": user.id})
            if tokens:
                await self._persist_interaction(
                    user_id=user.id,
                    question=f"utilisation report {period_start}..{period_end}",
                    intent="utilisation_report",
                    retrieved_ids=[],
                    answer="".join(tokens).strip(),
                    model_name=settings.llm_model,
                    refused=False,
                    started_at=started_at,
                    prompt_version=PROMPT_VERSION_REPORT,
                    input_tokens=self._estimate_tokens(f"{period_start} {period_end}"),
                    output_tokens=self._estimate_tokens("".join(tokens)),
                )
            raise
        finally:
            if completed:
                await self._persist_interaction(
                    user_id=user.id,
                    question=f"utilisation report {period_start}..{period_end}",
                    intent="utilisation_report",
                    retrieved_ids=[],
                    answer="".join(tokens).strip(),
                    model_name=settings.llm_model,
                    refused=False,
                    started_at=started_at,
                    prompt_version=PROMPT_VERSION_REPORT,
                    input_tokens=self._estimate_tokens(f"{period_start} {period_end}"),
                    output_tokens=self._estimate_tokens("".join(tokens)),
                )

    async def _answer_navigation(self, question: str) -> tuple[str, list[dict[str, object]], list[int]]:
        results = await search_services(self.db, question, settings.retrieval_top_k)
        if not results:
            return "we don't offer that", [], []

        context = "\n---\n".join(
            f"[{item['department']}] {item['service_name']}. {item['content']}" for item in results
        )
        prompt = PROMPT_NAV_V1.format(clinic="SmartHealth", context=context, user_question=question)
        try:
            response = await self.provider.complete_json(prompt)
            if response.strip().startswith("{"):
                parsed = json.loads(response)
                answer = str(parsed.get("answer") or parsed.get("response") or "").strip()
                if answer:
                    return answer, self._citations_from_results(results), [item["service_id"] for item in results]
        except Exception:
            pass

        answer = (
            f"Based on the clinic services I found, the best match is {results[0]['service_name']} in {results[0]['department']}."
        )
        return answer, self._citations_from_results(results), [item["service_id"] for item in results]

    async def _answer_preparation(self, question: str) -> tuple[str, list[dict[str, object]], list[int]]:
        results = await search_services(self.db, question, settings.retrieval_top_k)
        if not results:
            return "we don't offer that", [], []

        service_ids = [item["service_id"] for item in results]
        services = [self.services.get_by_id(service_id) for service_id in service_ids]
        services = [service for service in services if service is not None]
        if not services:
            return "we don't offer that", [], []

        primary = services[0]
        instructions = (primary.preparation_instructions or "").strip()
        if instructions:
            answer = f"For {primary.name}, please {instructions.rstrip('.')}."
        else:
            answer = f"{primary.name} has no preparation instructions on file."
        return answer, self._citations_from_results(results), service_ids

    async def _answer_availability(self, question: str) -> tuple[str, list[dict[str, object]], list[int]]:
        results = await search_services(self.db, question, settings.retrieval_top_k)
        if not results:
            return "we don't offer that", [], []

        service_ids = [item["service_id"] for item in results]
        services = [service for service in (self.services.get_by_id(service_id) for service_id in service_ids) if service is not None]
        if not services:
            return "we don't offer that", [], []

        primary = services[0]
        available_slots = self.slots.list_by_service(primary.id, offset=0, limit=5, available_only=True)[0]
        if not available_slots:
            answer = f"{primary.name} is currently fully booked."
        else:
            openings = ", ".join(slot.start_datetime.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") for slot in available_slots[:3])
            answer = f"{primary.name} has {len(available_slots)} available slot(s). Next openings: {openings}."
        return answer, self._citations_from_results(results), service_ids

    async def _answer_own_appointments(self, question: str, user: User) -> tuple[str, list[dict[str, object]], list[int]]:
        patient = self.patients.get_by_user_id(user.id)
        provider = self.providers.get_by_user_id(user.id)
        if patient is None and provider is None:
            return "I can only discuss appointments linked to your own account.", [], []

        if patient is not None:
            appointments, _ = self.appointments.list_scoped(patient_id=patient.id, limit=5, offset=0)
        else:
            appointments, _ = self.appointments.list_scoped(provider_id=provider.id, limit=5, offset=0)

        if not appointments:
            return "I could not find any appointments on your account.", [], []

        items: list[str] = []
        retrieved_ids: list[int] = []
        for appointment in appointments[:3]:
            retrieved_ids.append(appointment.id)
            slot = appointment.slot
            scheduled = slot.start_datetime.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if slot and slot.start_datetime else "an unknown time"
            items.append(
                f"Appointment {appointment.id} with {appointment.service.name if appointment.service else 'your service'} is {appointment.status.value} for {scheduled}."
            )
        answer = " ".join(items)
        citations = [{"appointment_id": appointment_id} for appointment_id in retrieved_ids]
        return answer, citations, retrieved_ids

    def _refusal_message(self, acute: bool) -> str:
        base = (
            "I can't provide medical advice. Please contact urgent care or emergency services now"
            if acute
            else "I can't provide medical advice. Please contact the appropriate clinic service"
        )
        return f"{base}. {DISCLAIMER}"

    def _citations_from_results(self, results: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {
                "service_id": item["service_id"],
                "service_name": item["service_name"],
                "department": item["department"],
            }
            for item in results
        ]

    def _tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        return [f"{piece} " for piece in text.split()]

    def _estimate_tokens(self, text: str) -> int:
        return len(text.split()) if text else 0

    async def _persist_interaction(
        self,
        *,
        user_id: int,
        question: str,
        intent: str,
        retrieved_ids: list[int],
        answer: str,
        model_name: str,
        refused: bool,
        started_at: float,
        prompt_version: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        latency_ms = int((time.perf_counter() - started_at) * 1000)

        def _write() -> None:
            from app import db as db_module

            session = db_module.SessionLocal()
            try:
                AIInteractionRepository(session).create_interaction(
                    user_id=user_id,
                    question=question,
                    intent=intent,
                    retrieved_ids=retrieved_ids,
                    answer=answer,
                    model=model_name,
                    prompt_version=prompt_version,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    refused=refused,
                )
            finally:
                session.close()

        await asyncio.to_thread(_write)
