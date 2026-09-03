import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_ai_rate_limit
from app.core.authorization import Permission, require_permission
from app.core.logging import get_request_id
from app.core.sse import ai_streaming_response, assistant_stream_error, format_sse_event
from app.models import User
from app.schemas.assistant import AssistantAskRequest, AssistantAskResponse, AssistantJsonAnswer
from app.services.assistant_service import AssistantService
from app.core.ai_controls import AIRedisStore, get_ai_redis_store

router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or get_request_id()


@router.post(
    "/ask",
    response_model=AssistantAskResponse,
    summary="Ask the healthcare navigation assistant",
    description="Return one standard JSON assistant answer with citations.",
)
async def ask_assistant(
    payload: AssistantAskRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.AI_ASSISTANT_USE)),
    _: User = Depends(require_ai_rate_limit),
    ai_store: AIRedisStore = Depends(get_ai_redis_store),
):
    service = AssistantService(db, ai_store=ai_store)
    normalized_question = service.safety.normalize(payload.question)
    decision = service.safety.classify(normalized_question)
    conversation_history: list[dict[str, str]] = []
    if payload.conversation_id and not decision.refused:
        conversation_history = await service.get_conversation_history(payload.conversation_id, current_user.id)

    answer = ""
    citations: list[dict[str, object]] = []
    async for event in service.stream_answer(
        normalized_question,
        current_user,
        payload.conversation_id,
        conversation_history,
    ):
        if event["type"] == "text":
            answer += str(event["value"])
        elif event["type"] == "citations":
            citations = event["value"]
        elif event["type"] == "error":
            return AssistantAskResponse(
                success=False,
                data=AssistantJsonAnswer(answer=str(event["value"].get("message", "Assistant request failed")), citations=[]),
                request_id=_request_id(request),
            )

    return AssistantAskResponse(
        data=AssistantJsonAnswer(answer=answer.strip(), citations=citations, refused=decision.refused),
        request_id=_request_id(request),
    )


@router.post("/ask/stream", response_model=None, response_class=StreamingResponse, summary="Stream the healthcare navigation assistant")
async def ask_assistant_stream(
    payload: AssistantAskRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.AI_ASSISTANT_USE)),
    _: User = Depends(require_ai_rate_limit),
    ai_store: AIRedisStore = Depends(get_ai_redis_store),
):
    service = AssistantService(db, ai_store=ai_store)
    normalized_question = service.safety.normalize(payload.question)
    decision = service.safety.classify(normalized_question)
    conversation_history: list[dict[str, str]] = []
    if payload.conversation_id and not decision.refused:
        conversation_history = await service.get_conversation_history(payload.conversation_id, current_user.id)

    async def events() -> AsyncIterator[str]:
        request_id = _request_id(request)
        citations: list[dict[str, object]] = []
        final_answer = ""
        had_error = False
        error_detail: dict[str, object] | None = None

        try:
            if decision.refused:
                refusal = service._refusal_message(decision.acute)
                persistence_task = asyncio.create_task(
                    service.persist_safety_refusal(normalized_question, current_user, decision)
                )
                yield format_sse_event("text", {"token": refusal})
                yield format_sse_event("citations", citations)
                yield format_sse_event("done", {"ok": True, "answer": refusal, "citations": citations})
                try:
                    await persistence_task
                except Exception:
                    logger.exception("Failed to persist assistant safety refusal")
                return

            async for event in service.stream_answer(
                normalized_question,
                current_user,
                payload.conversation_id,
                conversation_history,
            ):
                if event["type"] == "citations":
                    citations = event["value"]
                    yield format_sse_event("citations", citations)
                elif event["type"] == "text":
                    final_answer += event["value"]
                    yield format_sse_event("text", {"token": event["value"]})
                elif event["type"] == "error":
                    had_error = True
                    error_detail = {
                        **event["value"],
                        "request_id": request_id,
                    }
                    yield format_sse_event("error", {"error": error_detail})
                    break
                else:
                    logger.warning("Ignoring unknown assistant stream event type: %s", event.get("type"))

            if had_error:
                yield format_sse_event("done", {"ok": False, "error": error_detail})
            else:
                yield format_sse_event(
                    "done",
                    {"ok": True, "answer": final_answer.strip(), "citations": citations},
                )
        except Exception as exc:
            logger.exception("Assistant stream failed")
            err = assistant_stream_error(exc, request_id=request_id)
            yield format_sse_event("error", {"error": err})
            yield format_sse_event("done", {"ok": False, "error": err})

    return ai_streaming_response(events())
