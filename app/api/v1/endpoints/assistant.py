import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models import User
from app.schemas.assistant import AssistantAskRequest
from app.services.assistant_service import AssistantService
from app.core.rate_limit import limiter

router = APIRouter(prefix="/assistant", tags=["assistant"])


@limiter.limit("30/minute")
@router.post("/ask", summary="Ask the healthcare navigation assistant")
async def ask_assistant(
    payload: AssistantAskRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = AssistantService(db)

    async def events() -> AsyncIterator[str]:
        async for event in service.stream_answer(payload.question, current_user):
            if event["type"] == "citations":
                yield f"event: citations\ndata: {json.dumps(event['value'])}\n\n"
            else:
                yield f"data: {json.dumps({'token': event['value']})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")