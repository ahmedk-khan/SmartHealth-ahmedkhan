from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppError
from app.models import User, UserRole
from app.repositories import ProviderRepository
from app.schemas.domain import DepartmentCreate, DepartmentRead, PaginatedResponse, ProviderCreate, ProviderRead, ServiceCreate, ServiceRead, SlotCreate, SlotRead

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post(
    "",
    response_model=ProviderRead,
    status_code=status.HTTP_200_OK,
    summary="Create provider record",
    description="Creates or returns the provider profile associated with the authenticated user. Allowed for admin, front desk, and provider roles.",
)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    repository = ProviderRepository(db)
    provider = repository.get_by_user_id(current_user.id)
    if provider:
        return provider
    return repository.create_provider(current_user.id, payload.bio, payload.department_id)


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
    current_user: User = Depends(get_current_user),
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
def provider_slots(provider_id: int, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    repository = ProviderRepository(db)
    provider = repository.get_by_id(provider_id)
    if not provider:
        raise AppError("Provider not found", status_code=404, error_type="not_found")
    if current_user.role != UserRole.admin and current_user.role != UserRole.front_desk and current_user.role != UserRole.provider:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    items, total = repository.list_slots(provider_id=provider_id, offset=offset, limit=limit)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
