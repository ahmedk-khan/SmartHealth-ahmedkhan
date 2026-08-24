from app.models import Department, Service, ServiceStatus
from app.repositories.base import BaseRepository


class ServiceRepository(BaseRepository):
    def get_by_id(self, service_id: int) -> Service | None:
        return self.db.query(Service).filter(Service.id == service_id).first()

    def get_for_publication(self, service_id: int) -> Service | None:
        return self.db.query(Service).filter(Service.id == service_id).first()

    def mark_publishing(self, service: Service) -> None:
        service.status = ServiceStatus.PUBLISHING
        self.db.add(service)
        self.audit("service", service.id, "publishing", after={"status": service.status.value})
        self.db.commit()

    def mark_published(self, service: Service) -> None:
        service.status = ServiceStatus.PUBLISHED
        service.is_published = True
        self.db.add(service)
        self.audit("service", service.id, "published", after={"status": service.status.value})
        self.db.commit()

    def mark_publish_failed(self, service: Service) -> None:
        service.status = ServiceStatus.PUBLISH_FAILED
        service.is_published = False
        self.db.add(service)
        self.audit("service", service.id, "publish_failed", after={"status": service.status.value})
        self.db.commit()

    def department_exists(self, department_id: int) -> bool:
        return self.db.query(Department).filter(Department.id == department_id).first() is not None

    def create_service(self, data: dict) -> Service:
        service = Service(**data)
        self.db.add(service)
        self.db.flush()
        self.audit("service", service.id, "created", after={"status": service.status.value, "department_id": service.department_id})
        self.db.commit()
        self.db.refresh(service)
        return service

    def update_service(self, service: Service, data: dict) -> Service:
        for field, value in data.items():
            setattr(service, field, value)
        self.db.add(service)
        self.audit("service", service.id, "updated", after={"name": service.name, "department_id": service.department_id})
        self.db.commit()
        self.db.refresh(service)
        return service

    def publish(self, service: Service) -> Service:
        service.status = ServiceStatus.PUBLISHED
        service.is_published = True
        self.db.add(service)
        self.audit("service", service.id, "published", after={"status": service.status.value})
        self.db.commit()
        self.db.refresh(service)
        return service

    def unpublish(self, service: Service) -> Service:
        service.status = ServiceStatus.UNPUBLISHED
        service.is_published = False
        self.db.add(service)
        self.audit("service", service.id, "unpublished", after={"status": service.status.value})
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

    def list_all(self, offset: int, limit: int) -> tuple[list[Service], int]:
        query = self.db.query(Service)
        total = query.count()
        items = query.order_by(Service.id).offset(offset).limit(limit).all()
        return items, total