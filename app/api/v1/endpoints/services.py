from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models import Department, Service, User, UserRole
from app.schemas.domain import PaginatedResponse, ServiceCreate, ServiceRead

router = APIRouter(prefix="/services", tags=["services"])


@router.post("", response_model=ServiceRead, status_code=status.HTTP_200_OK)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")
    if not db.query(Department).filter(Department.id == payload.department_id).first():
        raise ValueError("Department not found")
    service = Service(**payload.model_dump())
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


@router.get("", response_model=PaginatedResponse[ServiceRead])
def list_services(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Service).filter(Service.is_published.is_(True))
    total = query.count()
    items = query.order_by(Service.id).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}
