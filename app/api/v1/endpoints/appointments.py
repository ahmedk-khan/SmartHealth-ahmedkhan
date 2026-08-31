from typing import Optional
from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.authorization import require_permission, Permission
from app.models import User, VisitStatus
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead, PaginatedResponse, WaitlistEntryRead
from app.services.appointment_service import AppointmentService

from app.core.logging import get_correlation_id

router = APIRouter(prefix="/appointments", tags=["appointments"])


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
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.APPOINTMENT_CANCEL))):
    return AppointmentService(db).cancel(appointment_id, current_user)


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

