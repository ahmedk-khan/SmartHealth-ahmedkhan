from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db, require_role
from app.models import Department, Patient, Provider, Service, Slot, SlotStatus, User, UserRole
from app.schemas.domain import DepartmentCreate, DepartmentRead, PaginatedResponse, ProviderCreate, ProviderRead, ServiceCreate, ServiceRead, SlotCreate, SlotRead

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("", response_model=ProviderRead, status_code=status.HTTP_200_OK)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")
    provider = db.query(Provider).filter(Provider.user_id == current_user.id).first()
    if provider:
        return provider
    provider = Provider(user_id=current_user.id, bio=payload.bio, department_id=payload.department_id)
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


@router.get("", response_model=PaginatedResponse[ProviderRead])
def list_providers(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        raise PermissionError("Forbidden")
    query = db.query(Provider)
    total = query.count()
    items = query.order_by(Provider.id).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{provider_id}/slots", response_model=PaginatedResponse[SlotRead])
def provider_slots(provider_id: int, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    provider = db.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        raise ValueError("Provider not found")
    if current_user.role != UserRole.admin and current_user.role != UserRole.front_desk and current_user.role != UserRole.provider:
        raise PermissionError("Forbidden")
    query = db.query(Slot).filter(Slot.provider_id == provider_id)
    total = query.count()
    items = query.order_by(Slot.start_datetime).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}
