import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.authorization import require_permission
from app.core.dependencies import get_current_user, get_db
from app.models import User
from app.schemas.assistant import AssistantAskRequest
from app.services.assistant_service import AssistantService
from app.core.ai_controls import ai_redis_store

router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)


@router.post("/ask", summary="Ask the healthcare navigation assistant")
async def ask_assistant(
    payload: AssistantAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = AssistantService(db)
    normalized_question = service.safety.normalize(payload.question)
    decision = service.safety.classify(normalized_question)
    if not decision.refused and not await ai_redis_store.allow_request(current_user.id):
        raise HTTPException(status_code=429, detail="AI request rate limit exceeded")
    conversation_history = []
    if payload.conversation_id and not decision.refused:
        conversation_history = await service.get_conversation_history(payload.conversation_id, current_user.id)

    async def events() -> AsyncIterator[str]:
        citations: list[dict[str, object]] = []
        final_answer = ""
        if decision.refused:
            refusal = service._refusal_message(decision.acute)
            persistence_task = asyncio.create_task(
                service.persist_safety_refusal(normalized_question, current_user, decision)
            )
            yield f"event: text\ndata: {json.dumps({'token': refusal})}\n\n"
            yield f"event: citations\ndata: {json.dumps(citations)}\n\n"
            yield f"event: done\ndata: {json.dumps({'answer': refusal, 'citations': citations})}\n\n"
            try:
                await persistence_task
            except Exception:
                logger.exception("Failed to persist assistant safety refusal")
            return
        async for event in service.stream_answer(normalized_question, current_user, payload.conversation_id, conversation_history):
            if event["type"] == "citations":
                citations = event["value"]
                yield f"event: citations\ndata: {json.dumps(citations)}\n\n"
            elif event["type"] == "text":
                final_answer += event["value"]
                yield f"event: text\ndata: {json.dumps({'token': event['value']})}\n\n"
            else:
                yield f"data: {json.dumps({'token': event['value']})}\n\n"
        yield f"event: done\ndata: {json.dumps({'answer': final_answer.strip(), 'citations': citations})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


