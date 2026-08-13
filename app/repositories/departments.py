from sqlalchemy.orm import Session

from app.models import Department
from app.repositories.base import BaseRepository


class DepartmentRepository(BaseRepository):
    def create_department(self, name: str, description: str | None) -> Department:
        department = Department(name=name, description=description)
        self.db.add(department)
        self.db.commit()
        self.db.refresh(department)
        return department

    def list_departments(self, offset: int, limit: int) -> tuple[list[Department], int]:
        query = self.db.query(Department)
        total = query.count()
        items = query.order_by(Department.id).offset(offset).limit(limit).all()
        return items, total