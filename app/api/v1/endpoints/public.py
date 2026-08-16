from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.repositories import ServiceRepository
from app.schemas.domain import PaginatedResponse, ServiceRead

router = APIRouter(prefix="/public", tags=["public"])


@router.get(
    "/services",
    response_model=PaginatedResponse[ServiceRead],
    summary="List public services",
    description="Returns a paginated list of published services for public browsing and patient discovery.",
)
def public_services(search: str | None = None, department_id: int | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    repository = ServiceRepository(db)
    items, total = repository.list_published(offset=offset, limit=limit, search=search)
    if department_id is not None:
        items = [service for service in items if service.department_id == department_id]
        total = len(items)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
