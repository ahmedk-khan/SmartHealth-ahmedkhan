import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.authorization import Permission, require_permission
from app.core.dependencies import get_db, require_ai_rate_limit
from app.core.logging import get_request_id
from app.core.sse import ai_streaming_response, sse_error_events, stream_generation_payload
from app.models import User
from app.schemas.assistant import AssistantReportRequest, ReportJsonResponse
from app.services.communication_service import CommunicationService
from app.services.llm_provider import get_llm_provider

router = APIRouter(prefix="/reports", tags=["reports"])
logger = logging.getLogger(__name__)


@router.post(
    "/generate/utilisation",
    response_model=ReportJsonResponse,
    summary="Generate utilisation report",
    description="Generate one grounded utilisation report as a standard JSON response.",
)
async def generate_utilisation_report(
    payload: AssistantReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.ANALYTICS_READ)),
    _: User = Depends(require_ai_rate_limit),
):
    result = await CommunicationService(db, get_llm_provider()).generate_utilisation_report(
        period_start=payload.period_start,
        period_end=payload.period_end,
        current_user=current_user,
    )
    return ReportJsonResponse(data=result.report, metadata=result.metadata)


@router.post(
    "/generate/utilisation/stream",
    response_model=None,
    response_class=StreamingResponse,
    summary="Generate utilisation report",
    description=(
        "Streams a department utilisation report as Server-Sent Events. "
        "Events: `text` (progressive summary tokens), `content` (structured UtilisationReport), "
        "`metadata`, `report`, `citations`, `done` (terminal payload with ok=true)."
    ),
    responses={
        200: {"description": "SSE stream of report generation events", "content": {"text/event-stream": {}}},
        401: {"description": "Authentication required"},
        403: {"description": "Analytics read permission required"},
        422: {"description": "Invalid date range"},
        429: {"description": "AI rate limit exceeded"},
    },
)
async def generate_utilisation_report_stream(
    payload: AssistantReportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.ANALYTICS_READ)),
    _: User = Depends(require_ai_rate_limit),
):
    request_id = getattr(request.state, "request_id", None) or get_request_id()

    async def events() -> AsyncIterator[str]:
        try:
            service = CommunicationService(db, get_llm_provider())
            result = await service.generate_utilisation_report(
                period_start=payload.period_start,
                period_end=payload.period_end,
                current_user=current_user,
            )
            report = result.report.model_dump(mode="json")
            metadata = result.metadata.model_dump(mode="json")
            stream_text = CommunicationService.format_utilisation_report_text(result.report)
            citations = [
                {
                    "source": "analytics_daily",
                    "period_start": report["period_start"],
                    "period_end": report["period_end"],
                }
            ]
            async for frame in stream_generation_payload(
                stream_text=stream_text,
                content=report,
                metadata=metadata,
                report=report,
                citations=citations,
            ):
                yield frame
        except Exception as exc:
            logger.exception("Utilisation report generation failed")
            for frame in sse_error_events(exc, request_id=request_id):
                yield frame

    return ai_streaming_response(events())



