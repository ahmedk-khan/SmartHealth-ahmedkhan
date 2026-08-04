from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models import Service
from app.schemas.domain import PaginatedResponse, ServiceRead

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/services", response_model=PaginatedResponse[ServiceRead])
def public_services(search: str | None = None, department_id: int | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = db.query(Service).filter(Service.is_published.is_(True))
    if search:
        query = query.filter(Service.name.contains(search))
    if department_id is not None:
        query = query.filter(Service.department_id == department_id)
    total = query.count()
    items = query.order_by(Service.id).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}
