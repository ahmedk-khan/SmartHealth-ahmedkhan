import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.authorization import Permission, require_permission
from app.core.dependencies import get_current_user, get_db
from app.models import User
from app.schemas.assistant import AssistantAskRequest, AssistantReportRequest
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
    normalized_question = service.safety.normalize(payload.question)

    async def events() -> AsyncIterator[str]:
        citations: list[dict[str, object]] = []
        final_answer = ""
        async for event in service.stream_answer(normalized_question, current_user):
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


@limiter.limit("20/minute")
@router.post("/report", summary="Generate a utilisation report")
async def generate_utilisation_report(
    payload: AssistantReportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.ANALYTICS_READ)),
):
    service = AssistantService(db)

    async def events() -> AsyncIterator[str]:
        report_payload: dict[str, object] | None = None
        async for event in service.stream_report(payload.period_start.isoformat(), payload.period_end.isoformat(), current_user):
            if event["type"] == "citations":
                yield f"event: citations\ndata: {json.dumps(event['value'])}\n\n"
            elif event["type"] == "text":
                yield f"event: text\ndata: {json.dumps({'token': event['value']})}\n\n"
            elif event["type"] == "report":
                report_payload = event["value"]
            else:
                continue
        if report_payload is None:
            report_payload = {
                "period_start": payload.period_start.isoformat(),
                "period_end": payload.period_end.isoformat(),
            }
        yield f"event: done\ndata: {json.dumps({'report': report_payload})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
