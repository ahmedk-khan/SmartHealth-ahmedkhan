from app.models import Department
from app.repositories.base import BaseRepository


class DepartmentRepository(BaseRepository):
    def get_by_name(self, name: str) -> Department | None:
        """Return a department by exact name or None."""
        return self.db.query(Department).filter(Department.name == name).first()

    def get_by_id(self, department_id: int) -> Department | None:
        return self.db.query(Department).filter(Department.id == department_id).first()

    def create_department(self, name: str, description: str | None) -> Department:
        department = Department(name=name, description=description)
        self.save_and_refresh(department)
        return department

    def list_departments(self, offset: int, limit: int) -> tuple[list[Department], int]:
        query = self.db.query(Department)
        total = query.count()
        items = query.order_by(Department.id).offset(offset).limit(limit).all()
        return items, total
