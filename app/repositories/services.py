from sqlalchemy.orm import Session

from app.models import Department, Service, ServiceStatus
from app.repositories.base import BaseRepository


class ServiceRepository(BaseRepository):
    def get_by_id(self, service_id: int) -> Service | None:
        return self.db.query(Service).filter(Service.id == service_id).first()

    def department_exists(self, department_id: int) -> bool:
        return self.db.query(Department).filter(Department.id == department_id).first() is not None

    def create_service(self, data: dict) -> Service:
        service = Service(**data)
        self.db.add(service)
        self.db.commit()
        self.db.refresh(service)
        return service

    def publish(self, service: Service) -> Service:
        service.status = ServiceStatus.PUBLISHED
        service.is_published = True
        self.db.add(service)
        self.db.commit()
        self.db.refresh(service)
        return service

    def unpublish(self, service: Service) -> Service:
        service.status = ServiceStatus.UNPUBLISHED
        service.is_published = False
        self.db.add(service)
        self.db.commit()
        self.db.refresh(service)
        return service

    def list_published(self, offset: int, limit: int, search: str | None = None) -> tuple[list[Service], int]:
        query = self.db.query(Service).filter(Service.is_published.is_(True))
        if search:
            query = query.filter(Service.name.ilike(f"%{search}%"))
        total = query.count()
        items = query.order_by(Service.id).offset(offset).limit(limit).all()
        return items, total