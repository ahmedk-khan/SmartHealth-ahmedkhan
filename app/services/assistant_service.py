import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import timezone
from uuid import UUID
from cryptography.fernet import Fernet, InvalidToken

from sqlalchemy.orm import Session

from app.core.authorization import Permission
from app.core.authorization.service import check_permission
from app.core.ai_controls import AIRedisStore
from app.core.logging import get_correlation_id
from app.core.metrics import record_ai_cache_hit, record_ai_interaction
from app.core.settings import settings
from app.core.sse import assistant_stream_error, error_payload
from app.models import User
from app.repositories import AIInteractionRepository, AppointmentRepository, GeneratedContentRepository, PatientRepository, ProviderRepository, ServiceRepository, SlotRepository
from app.services.assistant_prompts import DISCLAIMER, PROMPT_NAV_V1, PROMPT_VERSION_ASSISTANT, PROMPT_VERSION_REPORT
from app.services.llm_provider import LLMProvider, get_llm_provider
from app.services.safety_service import SafetyCheck
from app.services.search_service import search_services
from app.services.utilisation_service import UtilisationService


logger = logging.getLogger(__name__)


class AssistantService:
    def __init__(self, db: Session, provider: LLMProvider | None = None, *, ai_store: AIRedisStore) -> None:
        self.db = db
        self.provider = provider or get_llm_provider()
        self.ai_store = ai_store
        self.safety = SafetyCheck()
        self.appointments = AppointmentRepository(db)
        self.patients = PatientRepository(db)
        self.providers = ProviderRepository(db)
        self.services = ServiceRepository(db)
        self.slots = SlotRepository(db)

    async def get_conversation_history(self, conversation_id: UUID | None, user_id: int, limit: int = 5) -> list[dict[str, str]]:
        """
        Retrieve conversation history for multi-turn conversations.
        
        Returns list of {role: 'user'|'assistant', content: str} dicts.
        Only includes non-refused interactions to avoid including error states in history.
        """
        if not conversation_id:
            return []
        
        from app.models import AIInteraction
        
        interactions = self.db.query(AIInteraction).filter(
            AIInteraction.conversation_id == conversation_id,
            AIInteraction.user_id == user_id,
            AIInteraction.refused == False
        ).order_by(AIInteraction.created_at.desc()).limit(limit).all()
        
        # Build history in chronological order (oldest first)
        history = []
        for interaction in reversed(interactions):
            # Store question (can't use hash, need actual text for context)
            if interaction.question_text:
                try:
                    question_text = self._decrypt_question(interaction.question_text)
                except InvalidToken:
                    question_text = ""
                if question_text:
                    history.append({"role": "user", "content": question_text})
            if interaction.answer:
                history.append({"role": "assistant", "content": interaction.answer})
        
        return history

    async def stream_answer(self, question: str, user: User, conversation_id: UUID | None = None, conversation_history: list[dict[str, str]] | None = None) -> AsyncIterator[dict]:
        """
        Stream an answer to a user question with timeout protection.
        
        Applies asyncio.timeout to prevent indefinite hangs from LLM or retrieval.
        Falls back to a graceful error message if timeout occurs.
        """
        normalized = self.safety.normalize(question)
        decision = self.safety.classify(normalized)
        started_at = time.perf_counter()
        answer_parts: list[str] = []
        final_answer = ""
        citations: list[dict[str, object]] = []
        refused = False
        retrieved_ids: list[int] = []
        model_name = settings.llm_model
        token_source = " ".join(normalized.split())
        cache_hit = False

        try:
            async with asyncio.timeout(settings.llm_timeout_seconds):
                listing_question = self._is_service_listing_question(normalized)
                cache_scope = self._cache_user_scope(user)
                cached = (
                    await self.ai_store.get_cached_answer(
                        normalized,
                        user_scope=cache_scope,
                        model_id=model_name,
                        prompt_version=PROMPT_VERSION_ASSISTANT,
                    )
                    if decision.intent == "navigation" and not listing_question and not conversation_history
                    else None
                )
                if cached:
                    final_answer = str(cached.get("answer", ""))
                    citations = cached.get("citations", [])
                    cache_hit = True
                    record_ai_cache_hit()
                    for token in self._tokenize(final_answer):
                        answer_parts.append(token)
                        yield {"type": "text", "value": token}
                elif decision.refused:
                    answer = self._refusal_message(decision.acute)
                    final_answer = answer
                    refused = True
                    answer_parts = [answer]
                    yield {"type": "text", "value": answer}
                elif decision.intent == "appointment":
                    answer, citations, retrieved_ids = await self._answer_own_appointments(normalized, user)
                    final_answer = answer
                    for token in self._tokenize(answer):
                        answer_parts.append(token)
                        yield {"type": "text", "value": token}
                elif decision.intent == "preparation":
                    answer, citations, retrieved_ids = await self._answer_preparation(normalized)
                    final_answer = answer
                    for token in self._tokenize(answer):
                        answer_parts.append(token)
                        yield {"type": "text", "value": token}
                elif decision.intent == "availability":
                    answer, citations, retrieved_ids = await self._answer_availability(normalized)
                    final_answer = answer
                    for token in self._tokenize(answer):
                        answer_parts.append(token)
                        yield {"type": "text", "value": token}
                elif listing_question:
                    answer, citations, retrieved_ids = await self._answer_service_listing()
                    final_answer = answer
                    for token in self._tokenize(answer):
                        answer_parts.append(token)
                        yield {"type": "text", "value": token}
                elif decision.intent == "specialist_navigation":
                    answer, citations, retrieved_ids = await self._answer_specialist_navigation(normalized)
                    final_answer = answer
                    for token in self._tokenize(answer):
                        answer_parts.append(token)
                        yield {"type": "text", "value": token}
                else:
                    results = await search_services(self.db, normalized, settings.retrieval_top_k)
                    if not results:
                        answer = "we don't offer that"
                        final_answer = answer
                        citations = []
                        retrieved_ids = []
                        answer_parts = [answer]
                        yield {"type": "text", "value": answer}
                    else:
                        retrieved_ids = [item["service_id"] for item in results]
                        citations = self._citations_from_results(results)
                        if self._is_service_listing_question(normalized):
                            final_answer = self._format_service_listing(results)
                            for token in self._tokenize(final_answer):
                                answer_parts.append(token)
                                yield {"type": "text", "value": token}
                        else:
                            context = "\n---\n".join(
                                f"[{item['department']}] {item['service_name']}. {item['content']}" for item in results
                            )
                            prompt = PROMPT_NAV_V1.format(clinic="SmartHealth", context=context, user_question=normalized)
                            if conversation_history:
                                history = conversation_history[-10:]
                                history_context = "\n".join(
                                    f"{item['role'].capitalize()}: {item['content']}" for item in history
                                )
                                prompt = (
                                    f"{prompt}\n\nConversation history (for context only):\n"
                                    f"{history_context}"
                                )
                            async for token in self.provider.stream(prompt):
                                answer_parts.append(token)
                                yield {"type": "text", "value": token}
                            final_answer = "".join(answer_parts).strip() or (
                                f"Based on the clinic services I found, the best match is {results[0]['service_name']} in {results[0]['department']}."
                            )

                        if not listing_question:
                            await self.ai_store.cache_answer(
                                normalized,
                                final_answer,
                                citations,
                                user_scope=cache_scope,
                                model_id=model_name,
                                prompt_version=PROMPT_VERSION_ASSISTANT,
                            )

                yield {"type": "citations", "value": citations}
        except asyncio.TimeoutError:
            # Log timeout and persist partial answer
            error_msg = f"Assistant request timed out after {settings.llm_timeout_seconds}s"
            logger.warning(error_msg, extra={"user_id": user.id, "intent": decision.intent})
            partial_answer = "".join(answer_parts).strip() or "The request took too long. Please try again."
            final_answer = partial_answer
            yield {"type": "text", "value": " [Request timed out. Please try again.]"}
            yield {"type": "citations", "value": citations}
            await self._persist_interaction(
                user_id=user.id,
                question=normalized,
                intent=decision.intent,
                retrieved_ids=retrieved_ids,
                answer=final_answer,
                model_name=model_name,
                refused=False,
                started_at=started_at,
                prompt_version=PROMPT_VERSION_ASSISTANT,
                input_tokens=self._estimate_tokens(token_source),
                output_tokens=self._estimate_tokens("".join(answer_parts)),
                conversation_id=conversation_id,
                cache_hit=cache_hit,
            )
        except Exception as exc:
            err = assistant_stream_error(exc)
            yield {"type": "error", "value": err}
            await self._persist_interaction(
                user_id=user.id,
                question=normalized,
                intent=decision.intent,
                retrieved_ids=retrieved_ids,
                answer=err["message"],
                model_name=model_name,
                refused=False,
                started_at=started_at,
                prompt_version=PROMPT_VERSION_ASSISTANT,
                input_tokens=self._estimate_tokens(token_source),
                output_tokens=self._estimate_tokens(err["message"]),
                conversation_id=conversation_id,
                cache_hit=cache_hit,
            )
            return
        except asyncio.CancelledError:
            await self._persist_interaction(
                user_id=user.id,
                question=normalized,
                intent=decision.intent,
                retrieved_ids=retrieved_ids,
                answer=final_answer or "".join(answer_parts).strip(),
                model_name=model_name,
                refused=refused,
                started_at=started_at,
                prompt_version=PROMPT_VERSION_ASSISTANT,
                input_tokens=self._estimate_tokens(token_source),
                output_tokens=self._estimate_tokens("".join(answer_parts)),
                conversation_id=conversation_id,
                cache_hit=cache_hit,
            )
            logger.info("Assistant stream truncated by client disconnect", extra={"user_id": user.id, "intent": decision.intent})
            raise
        else:
            await self._persist_interaction(
                user_id=user.id,
                question=normalized,
                intent=decision.intent,
                retrieved_ids=retrieved_ids,
                answer=final_answer or "".join(answer_parts).strip(),
                model_name=model_name,
                refused=refused,
                started_at=started_at,
                prompt_version=PROMPT_VERSION_ASSISTANT,
                input_tokens=self._estimate_tokens(token_source),
                output_tokens=self._estimate_tokens("".join(answer_parts)),
                conversation_id=conversation_id,
                cache_hit=cache_hit,
            )

    async def stream_report(self, period_start: str, period_end: str, user: User) -> AsyncIterator[dict]:
        check_permission(user, Permission.ANALYTICS_READ)
        util_service = UtilisationService(self.db, self.provider)
        started_at = time.perf_counter()
        tokens: list[str] = []
        report_payload: dict[str, object] | None = None
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
            report_payload = raw_report.model_dump(mode="json")
            await self._persist_generated_content(
                content=report_payload,
                content_type="utilisation_report",
                report_scope=f"{period_start}..{period_end}",
                model_name=settings.llm_model,
                prompt_version=PROMPT_VERSION_REPORT,
            )
            report_json = json.dumps(report_payload, sort_keys=True)
            for token in self._tokenize(report_json):
                tokens.append(token)
                yield {"type": "text", "value": token}
            yield {"type": "report", "value": report_payload}
            yield {"type": "citations", "value": citations}
            completed = True
        except asyncio.CancelledError:
            logger.info("Assistant report stream truncated by client disconnect", extra={"user_id": user.id})
            await self._persist_interaction(
                user_id=user.id,
                question=f"utilisation report {period_start}..{period_end}",
                intent="utilisation_report",
                retrieved_ids=[],
                answer=json.dumps(report_payload, sort_keys=True) if report_payload is not None else "".join(tokens).strip(),
                model_name=settings.llm_model,
                refused=False,
                started_at=started_at,
                prompt_version=PROMPT_VERSION_REPORT,
                input_tokens=self._estimate_tokens(f"{period_start} {period_end}"),
                output_tokens=self._estimate_tokens("".join(tokens)) if report_payload is None else self._estimate_tokens(json.dumps(report_payload, sort_keys=True)),
            )
            raise
        finally:
            if completed:
                await self._persist_interaction(
                    user_id=user.id,
                    question=f"utilisation report {period_start}..{period_end}",
                    intent="utilisation_report",
                    retrieved_ids=[],
                    answer=json.dumps(report_payload, sort_keys=True) if report_payload is not None else "".join(tokens).strip(),
                    model_name=settings.llm_model,
                    refused=False,
                    started_at=started_at,
                    prompt_version=PROMPT_VERSION_REPORT,
                    input_tokens=self._estimate_tokens(f"{period_start} {period_end}"),
                    output_tokens=self._estimate_tokens(json.dumps(report_payload, sort_keys=True)) if report_payload is not None else self._estimate_tokens("".join(tokens)),
                )

    async def _answer_preparation(self, question: str) -> tuple[str, list[dict[str, object]], list[int]]:
        results = await search_services(self.db, question, settings.retrieval_top_k)
        if not results:
            return "we don't offer that", [], []

        service_ids = [item["service_id"] for item in results]
        services = await asyncio.gather(*(
            asyncio.to_thread(self.services.get_by_id, service_id) for service_id in service_ids
        ))
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

    async def _answer_service_listing(self) -> tuple[str, list[dict[str, object]], list[int]]:
        services, _ = await asyncio.to_thread(self.services.list_published, offset=0, limit=settings.retrieval_top_k)
        if not services:
            return "we don't offer that", [], []

        results = [
            {
                "service_id": service.id,
                "service_name": service.name,
                "department": service.department.name if service.department else "General",
            }
            for service in services
        ]
        return self._format_service_listing(results), self._citations_from_results(results), [service.id for service in services]

    async def _answer_availability(self, question: str) -> tuple[str, list[dict[str, object]], list[int]]:
        results = await search_services(self.db, question, settings.retrieval_top_k)
        if not results:
            return "we don't offer that", [], []

        service_ids = [item["service_id"] for item in results]
        services = [service for service in await asyncio.gather(*(
            asyncio.to_thread(self.services.get_by_id, service_id) for service_id in service_ids
        )) if service is not None]
        if not services:
            return "we don't offer that", [], []

        primary = services[0]
        available_slots = (await asyncio.to_thread(
            self.slots.list_by_service, primary.id, offset=0, limit=5, available_only=True
        ))[0]
        if not available_slots:
            answer = f"{primary.name} is currently fully booked."
        else:
            openings = ", ".join(slot.start_datetime.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") for slot in available_slots[:3])
            answer = f"{primary.name} has {len(available_slots)} available slot(s). Next openings: {openings}."
        return answer, self._citations_from_results(results), service_ids

    async def _answer_specialist_navigation(self, question: str) -> tuple[str, list[dict[str, object]], list[int]]:
        results = await search_services(self.db, question, settings.retrieval_top_k)
        if not results:
            return "We don't offer that here. This is not medical advice - please consult a professional.", [], []

        primary = self.services.get_by_id(results[0]["service_id"])
        if primary is None:
            return "We don't offer that here. This is not medical advice - please consult a professional.", [], []
        instructions = (primary.preparation_instructions or "No preparation instructions are listed.").strip()
        answer = (
            f"The closest available clinic service is {primary.name} in {results[0]['department']}. "
            f"Preparation: {instructions.rstrip('.')}. "
            "This is not medical advice - please consult a professional."
        )
        return answer, self._citations_from_results(results[:1]), [primary.id]

    async def _answer_own_appointments(self, question: str, user: User) -> tuple[str, list[dict[str, object]], list[int]]:
        patient, provider = await asyncio.gather(
            asyncio.to_thread(self.patients.get_by_user_id, user.id),
            asyncio.to_thread(self.providers.get_by_user_id, user.id),
        )
        if patient is None and provider is None:
            return "I can only discuss appointments linked to your own account.", [], []

        if patient is not None:
            appointments, _ = await asyncio.to_thread(
                self.appointments.list_scoped, patient_id=patient.id, limit=5, offset=0
            )
        else:
            appointments, _ = await asyncio.to_thread(
                self.appointments.list_scoped, provider_id=provider.id, limit=5, offset=0
            )

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

    def _is_service_listing_question(self, question: str) -> bool:
        words = set(question.lower().split())
        return "service" in words or "services" in words or "offer" in words or "offers" in words

    @staticmethod
    def _cache_user_scope(user: User) -> str:
        return f"{user.id}:{user.role.value}"

    def _format_service_listing(self, results: list[dict[str, object]]) -> str:
        seen: set[str] = set()
        names: list[str] = []
        for item in results:
            name = " ".join(str(item["service_name"]).split()).strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                names.append(f"{name} ({item['department']})")
        return "Available services: " + "; ".join(names) + "."

    def _tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        words = text.split()
        chunk_size = 6
        return [" ".join(words[index:index + chunk_size]) + " " for index in range(0, len(words), chunk_size)]

    def _estimate_tokens(self, text: str) -> int:
        return len(text.split()) if text else 0

    def _conversation_cipher(self) -> Fernet:
        import base64

        key_material = settings.ai_conversation_key or settings.jwt_secret
        key = base64.urlsafe_b64encode(hashlib.sha256(key_material.encode("utf-8")).digest())
        return Fernet(key)

    def _encrypt_question(self, question: str) -> str:
        return self._conversation_cipher().encrypt(question.encode("utf-8")).decode("ascii")

    def _decrypt_question(self, encrypted_question: str) -> str:
        return self._conversation_cipher().decrypt(encrypted_question.encode("ascii")).decode("utf-8")

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
        conversation_id: UUID | None = None,
        cache_hit: bool = False,
    ) -> None:
        latency_ms = int((time.perf_counter() - started_at) * 1000)

        def _write() -> None:
            from app import db as db_module

            session = db_module.SessionLocal()
            try:
                persisted_answer = answer
                if intent == "appointment":
                    persisted_answer = "[USER_SCOPED_CONTENT_REDACTED]"
                AIInteractionRepository(session).create_interaction(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    correlation_id=get_correlation_id(),
                    question=f"sha256:{hashlib.sha256(question.encode('utf-8')).hexdigest()}",
                    question_text=self._encrypt_question(question) if conversation_id else None,
                    intent=intent,
                    retrieved_ids=retrieved_ids,
                    answer=persisted_answer,
                    model=model_name,
                    prompt_version=prompt_version,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    refused=refused,
                    cache_hit=cache_hit,
                )
            finally:
                session.close()

        await asyncio.to_thread(_write)
        record_ai_interaction(
            intent=intent,
            outcome="refused" if refused else ("cache_hit" if cache_hit else "success"),
            latency_seconds=latency_ms / 1000,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            refused=refused,
        )

    async def persist_safety_refusal(self, question: str, user: User, decision: object) -> None:
        """Persist a safety refusal without invoking retrieval or an LLM provider."""
        await self._persist_interaction(
            user_id=user.id,
            question=question,
            intent=decision.intent,
            retrieved_ids=[],
            answer=self._refusal_message(decision.acute),
            model_name=settings.llm_model,
            refused=True,
            started_at=time.perf_counter(),
            prompt_version=PROMPT_VERSION_ASSISTANT,
            input_tokens=self._estimate_tokens(question),
            output_tokens=self._estimate_tokens(self._refusal_message(decision.acute)),
        )

    async def _persist_generated_content(
        self,
        *,
        content: dict[str, object],
        content_type: str,
        report_scope: str | None,
        model_name: str,
        prompt_version: str,
    ) -> None:
        def _write() -> None:
            from app import db as db_module

            session = db_module.SessionLocal()
            try:
                GeneratedContentRepository(session).create_generated_content(
                    type=content_type,
                    content=content,
                    report_scope=report_scope,
                    model=model_name,
                    prompt_version=prompt_version,
                )
            finally:
                session.close()

        await asyncio.to_thread(_write)
