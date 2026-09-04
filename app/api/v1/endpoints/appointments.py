import logging
from collections.abc import AsyncIterator
from typing import Optional
from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_ai_rate_limit
from app.core.authorization import Permission, require_permission
from app.core.authorization import require_permission, Permission
from app.core.logging import get_request_id
from app.core.sse import ai_streaming_response, sse_error_events, stream_generation_payload
from app.models import User, VisitStatus
from app.schemas.assistant import (
    AppointmentFollowupRequest,
    AppointmentFollowupResponse,
    AppointmentSummaryRequest,
    AppointmentSummaryResponse,
)
from app.schemas.domain import AppointmentCancelRequest, AppointmentCreate, AppointmentRead, BillingRead, PaginatedResponse, WaitlistEntryRead
from app.services.appointment_service import AppointmentService
from app.services.communication_service import CommunicationService
from app.services.llm_provider import get_llm_provider
from app.core.logging import get_correlation_id

router = APIRouter(prefix="/appointments", tags=["appointments"])
logger = logging.getLogger(__name__)


@router.post("/waitlist/{slot_id}", response_model=WaitlistEntryRead, status_code=status.HTTP_201_CREATED)
def join_waitlist(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.WAITLIST_JOIN))):
    return AppointmentService(db).join_waitlist(slot_id, current_user)


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.APPOINTMENT_CREATE)),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    correlation_id: Optional[str] = Header(
        default=None,
        alias="X-Correlation-ID",
    ),
):
    resolved_correlation_id = correlation_id or get_correlation_id()
    return await AppointmentService(db).create(
        payload=payload,
        current_user=current_user,
        idempotency_key=idempotency_key,
        correlation_id=resolved_correlation_id,
    )


@router.get("", response_model=PaginatedResponse[AppointmentRead])
def list_appointments(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.APPOINTMENT_READ)),
):
    return AppointmentService(db).list(limit, offset, current_user)


@router.get("/{appointment_id}/state", response_model=dict)
def get_appointment_state(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.APPOINTMENT_READ)),
):
    return AppointmentService(db).get_state(appointment_id, current_user)


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(
    appointment_id: int,
    payload: AppointmentCancelRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.APPOINTMENT_CANCEL)),
):
    return AppointmentService(db).cancel(appointment_id, current_user, payload.reason.strip() if payload and payload.reason else None)


@router.post("/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_appointment(
    appointment_id: int,
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.APPOINTMENT_UPDATE)),
):
    return AppointmentService(db).reschedule(appointment_id, payload.slot_id, current_user)


@router.post("/{appointment_id}/visit/check-in", response_model=dict)
def check_in_visit(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.VISIT_UPDATE)),
):
    return AppointmentService(db).transition_visit_status(appointment_id, VisitStatus.CHECKED_IN, current_user)


@router.post("/{appointment_id}/visit/start", response_model=dict)
def start_visit(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.VISIT_UPDATE)),
):
    return AppointmentService(db).transition_visit_status(appointment_id, VisitStatus.IN_PROGRESS, current_user)


@router.post("/{appointment_id}/visit/complete", response_model=dict)
def complete_visit(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.VISIT_UPDATE)),
):
    return AppointmentService(db).transition_visit_status(appointment_id, VisitStatus.COMPLETED, current_user)


@router.post("/{appointment_id}/no-show", response_model=AppointmentRead)
def mark_no_show(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.APPOINTMENT_UPDATE))):
    return AppointmentService(db).mark_no_show(appointment_id, current_user)


@router.post("/{appointment_id}/billing/pre-check", response_model=BillingRead)
def billing_pre_check(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.BILLING_CREATE))):
    return AppointmentService(db).billing_pre_check(appointment_id, current_user)


@router.post(
    "/{appointment_id}/generate/summary",
    response_model=AppointmentSummaryResponse,
    summary="Generate appointment summary",
    description="Generate one patient-facing appointment summary as a standard JSON response.",
)
async def generate_appointment_summary(
    appointment_id: int,
    payload: AppointmentSummaryRequest = AppointmentSummaryRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.COMMUNICATION_GENERATE)),
    _: User = Depends(require_ai_rate_limit),
):
    summary, metadata = await CommunicationService(db, get_llm_provider()).generate_appointment_summary(
        appointment_id=appointment_id,
        current_user=current_user,
        include_instructions=payload.include_instructions,
        include_cancellation_policy=payload.include_cancellation_policy,
    )
    return AppointmentSummaryResponse(
        data=summary,
        metadata=metadata,
    )


@router.post(
    "/{appointment_id}/generate/summary/stream",
    response_model=None,
    response_class=StreamingResponse,
    summary="Generate appointment summary",
    description=(
        "Streams a patient-facing appointment summary as Server-Sent Events. "
        "Events: `text` (progressive tokens), `content` (structured AppointmentSummary), "
        "`metadata` (audit record), `done` (terminal payload with ok=true)."
    ),
    responses={
        200: {"description": "SSE stream of generation events", "content": {"text/event-stream": {}}},
        401: {"description": "Authentication required"},
        403: {"description": "Admin or front-desk role required"},
        404: {"description": "Appointment not found"},
        429: {"description": "AI rate limit exceeded"},
        502: {"description": "Generated content failed safety or validation checks"},
        503: {"description": "LLM provider unavailable or not configured"},
    },
)
async def generate_appointment_summary_stream(
    appointment_id: int,
    request: Request,
    payload: AppointmentSummaryRequest = AppointmentSummaryRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.COMMUNICATION_GENERATE)),
    _: User = Depends(require_ai_rate_limit),
):
    request_id = getattr(request.state, "request_id", None) or get_request_id()

    async def events() -> AsyncIterator[str]:
        try:
            service = CommunicationService(db, get_llm_provider())
            summary, metadata = await service.generate_appointment_summary(
                appointment_id=appointment_id,
                current_user=current_user,
                include_instructions=payload.include_instructions,
                include_cancellation_policy=payload.include_cancellation_policy,
            )
            content = summary.model_dump(mode="json")
            metadata_payload = metadata.model_dump(mode="json")
            async for frame in stream_generation_payload(
                stream_text=summary.summary,
                content=content,
                metadata=metadata_payload,
                text_chunk_size=len(summary.summary),
            ):
                yield frame
        except Exception as exc:
            logger.exception("Appointment summary generation failed", extra={"appointment_id": appointment_id})
            for frame in sse_error_events(exc, request_id=request_id):
                yield frame

    return ai_streaming_response(events())


@router.post(
    "/{appointment_id}/generate/followup",
    response_model=AppointmentFollowupResponse,
    summary="Generate appointment follow-up",
    description="Generate one staff follow-up draft as a standard JSON response.",
)
async def generate_appointment_followup(
    appointment_id: int,
    payload: AppointmentFollowupRequest = AppointmentFollowupRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.COMMUNICATION_GENERATE)),
    _: User = Depends(require_ai_rate_limit),
):
    followup, metadata = await CommunicationService(db, get_llm_provider()).generate_appointment_followup(
        appointment_id=appointment_id,
        current_user=current_user,
        tone=payload.tone,
        include_next_steps=payload.include_next_steps,
    )
    return AppointmentFollowupResponse(
        data=followup,
        metadata=metadata,
    )


@router.post(
    "/{appointment_id}/generate/followup/stream",
    response_model=None,
    response_class=StreamingResponse,
    summary="Generate appointment follow-up",
    description=(
        "Streams a staff follow-up communication draft as Server-Sent Events. "
        "Events: `text` (progressive body tokens), `content` (structured AppointmentFollowup), "
        "`metadata` (audit record), `done` (terminal payload with ok=true)."
    ),
    responses={
        200: {"description": "SSE stream of generation events", "content": {"text/event-stream": {}}},
        401: {"description": "Authentication required"},
        403: {"description": "Admin or front-desk role required"},
        404: {"description": "Appointment not found"},
        429: {"description": "AI rate limit exceeded"},
        502: {"description": "Generated content failed safety or validation checks"},
        503: {"description": "LLM provider unavailable or not configured"},
    },
)
async def generate_appointment_followup_stream(
    appointment_id: int,
    request: Request,
    payload: AppointmentFollowupRequest = AppointmentFollowupRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.COMMUNICATION_GENERATE)),
    _: User = Depends(require_ai_rate_limit),
):
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    logger.info(
        "Starting appointment follow-up generation",
        extra={"appointment_id": appointment_id, "request_id": request_id, "user_id": current_user.id},
    )

    async def events() -> AsyncIterator[str]:
        try:
            service = CommunicationService(db, get_llm_provider())
            followup, metadata = await service.generate_appointment_followup(
                appointment_id=appointment_id,
                current_user=current_user,
                tone=payload.tone,
                include_next_steps=payload.include_next_steps,
            )
            content = followup.model_dump(mode="json")
            metadata_payload = metadata.model_dump(mode="json")
            async for frame in stream_generation_payload(
                stream_text=followup.body,
                content=content,
                metadata=metadata_payload,
                text_chunk_size=len(followup.body),
            ):
                yield frame
            logger.info(
                "Completed appointment follow-up generation",
                extra={"appointment_id": appointment_id, "request_id": request_id, "user_id": current_user.id},
            )
        except Exception as exc:
            logger.exception("Appointment follow-up generation failed", extra={"appointment_id": appointment_id})
            for frame in sse_error_events(exc, request_id=request_id):
                yield frame

    return ai_streaming_response(events())

