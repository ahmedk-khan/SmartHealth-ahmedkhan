from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.authorization import require_permission, Permission, ProviderOwnershipGuard
from app.core.exceptions import (
    AppError,
    ForbiddenError,
    ValidationError,
    ProviderNotFoundError,
    DepartmentNotFoundError,
)
from app.models import User, UserRole
from app.repositories import AuthRepository, DepartmentRepository, ProviderRepository
from app.schemas.domain import PaginatedResponse, ProviderCreate, ProviderRead, ProviderUpdate, ServiceRead, SlotRead
from app.services.healthcare_event_service import HealthcareEventService

router = APIRouter(prefix="/providers", tags=["providers"])


def _resolve_provider_for_current_user(repository: ProviderRepository, provider_id: int, current_user: User):
    provider = repository.get_by_id(provider_id)
    if current_user.role != UserRole.provider:
        return provider

    own_provider = repository.get_by_user_id(current_user.id)
    if own_provider is None:
        return provider

    # Swagger users often copy the authenticated user id, while the route is
    # addressed by provider record id. Accept either identifier for the owner.
    if provider and provider.user_id == current_user.id:
        return provider
    if provider_id == current_user.id:
        return own_provider
    return provider


@router.post(
    "",
    response_model=ProviderRead,
    status_code=status.HTTP_200_OK,
    summary="Create provider record",
    description="Creates or returns the provider profile associated with the authenticated user. Allowed for admin, front desk, and provider roles.",
)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.PROVIDER_CREATE))):
    repository = ProviderRepository(db)
    target_user_id = payload.user_id if current_user.role == UserRole.admin and payload.user_id else current_user.id
    target_user = AuthRepository(db).get_user_by_id(target_user_id)
    if not target_user or target_user.role != UserRole.provider:
        raise ValidationError("A provider user account is required", code="INVALID_PROVIDER_USER")
    provider = repository.get_by_user_id(target_user_id)
    if provider:
        return provider
    provider = repository.create_provider(target_user_id, payload.bio, payload.department_id, payload.specialty)
    HealthcareEventService(db).publish_resource_event("provider.created", entity_type="provider", entity_id=provider.id, department_id=provider.department_id)
    return provider


@router.patch("/{provider_id}", response_model=ProviderRead, summary="Update provider profile")
def update_provider(provider_id: int, payload: ProviderUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.PROVIDER_UPDATE))):
    repository = ProviderRepository(db)
    provider = _resolve_provider_for_current_user(repository, provider_id, current_user)
    if not provider:
        raise ProviderNotFoundError()
    ProviderOwnershipGuard(current_user, provider).enforce()
    if payload.department_id is not None and not DepartmentRepository(db).get_by_id(payload.department_id):
        raise DepartmentNotFoundError()
    return repository.update_profile(provider, payload.model_dump(exclude_unset=True))


@router.get(
    "",
    response_model=PaginatedResponse[ProviderRead],
    summary="List providers",
    description="Returns a paginated list of providers available in the system.",
)
def list_providers(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.PROVIDER_READ)),
):
    repository = ProviderRepository(db)
    items, total = repository.list_providers(offset=offset, limit=limit)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{provider_id}/slots",
    response_model=PaginatedResponse[SlotRead],
    summary="List provider slots",
    description="Returns the paginated slot list for a specific provider while enforcing role-based access.",
)
def provider_slots(provider_id: int, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SLOT_READ))):
    repository = ProviderRepository(db)
    provider = repository.get_by_id(provider_id)
    if not provider:
        raise ProviderNotFoundError()
    ProviderOwnershipGuard(current_user, provider).enforce()
    items, total = repository.list_slots(provider_id=provider_id, offset=offset, limit=limit)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{provider_id}/services",
    response_model=PaginatedResponse[ServiceRead],
    summary="List provider services",
    description="Returns the services explicitly linked to a provider profile.",
)
def provider_services(provider_id: int, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SERVICE_READ))):
    repository = ProviderRepository(db)
    provider = repository.get_by_id(provider_id)
    if not provider:
        raise ProviderNotFoundError()
    ProviderOwnershipGuard(current_user, provider).enforce()
    items, total = repository.list_services(provider_id=provider_id, offset=offset, limit=limit)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
