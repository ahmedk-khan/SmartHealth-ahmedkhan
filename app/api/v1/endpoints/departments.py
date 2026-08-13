from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.models import User, UserRole
from app.repositories import DepartmentRepository
from app.schemas.domain import DepartmentCreate, DepartmentRead, PaginatedResponse

router = APIRouter(prefix="/departments", tags=["departments"])


@router.post("", response_model=DepartmentRead, status_code=status.HTTP_200_OK)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    repository = DepartmentRepository(db)
    department = repository.create_department(payload.name, payload.description)
    return department


@router.get("", response_model=PaginatedResponse[DepartmentRead])
def list_departments(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    repository = DepartmentRepository(db)
    items, total = repository.list_departments(offset=offset, limit=limit)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
