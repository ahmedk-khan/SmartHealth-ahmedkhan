from app.models import Department, Service, ServiceStatus
from app.repositories.base import BaseRepository


class ServiceRepository(BaseRepository):
    def get_by_name(self, name: str) -> Service | None:
        """Return a service by exact name or None."""
        return self.db.query(Service).filter(Service.name == name).first()

    def create_seed_service(self, data: dict) -> Service:
        """Create and refresh a seed service without adding audit records."""
        service = Service(**data)
        self.add(service)
        self.commit()
        self.refresh(service)
        return service

    def get_by_id(self, service_id: int) -> Service | None:
        return self.db.query(Service).filter(Service.id == service_id).first()

    def get_for_publication(self, service_id: int) -> Service | None:
        return self.db.query(Service).filter(Service.id == service_id).first()

    def mark_publishing(self, service: Service) -> None:
        service.status = ServiceStatus.PUBLISHING
        self.add(service)
        self.audit("service", service.id, "publishing", after={"status": service.status.value})
        self.commit()

    def mark_published(self, service: Service, *, commit: bool = True) -> None:
        service.status = ServiceStatus.PUBLISHED
        service.is_published = True
        self.add(service)
        self.audit("service", service.id, "published", after={"status": service.status.value})
        if commit:
            self.commit()

    def mark_publish_failed(self, service: Service) -> None:
        service.status = ServiceStatus.PUBLISH_FAILED
        service.is_published = False
        self.add(service)
        self.audit("service", service.id, "publish_failed", after={"status": service.status.value})
        self.commit()

    def recover_stale_publishing(self, service: Service, stale_minutes: int) -> Service:
        """Mark long-running PUBLISHING services as failed so they can be retried."""
        if service.status != ServiceStatus.PUBLISHING:
            return service

        import datetime

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=stale_minutes)
        updated_at = service.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=datetime.timezone.utc)
        if updated_at < cutoff:
            self.mark_publish_failed(service)
            self.refresh(service)
        return service

    def department_exists(self, department_id: int) -> bool:
        return self.db.query(Department).filter(Department.id == department_id).first() is not None

    def create_service(self, data: dict) -> Service:
        service = Service(**data)
        self.add(service)
        self.flush()
        self.audit("service", service.id, "created", after={"status": service.status.value, "department_id": service.department_id})
        self.commit()
        self.refresh(service)
        return service

    def update_service(self, service: Service, data: dict) -> Service:
        for field, value in data.items():
            setattr(service, field, value)
        self.add(service)
        self.audit("service", service.id, "updated", after={"name": service.name, "department_id": service.department_id})
        self.commit()
        self.refresh(service)
        return service

    def publish(self, service: Service) -> Service:
        service.status = ServiceStatus.PUBLISHED
        service.is_published = True
        self.add(service)
        self.audit("service", service.id, "published", after={"status": service.status.value})
        self.commit()
        self.refresh(service)
        return service

    def unpublish(self, service: Service) -> Service:
        service.status = ServiceStatus.UNPUBLISHED
        service.is_published = False
        self.add(service)
        self.audit("service", service.id, "unpublished", after={"status": service.status.value})
        self.commit()
        self.refresh(service)
        return service

    def list_published(self, offset: int, limit: int, search: str | None = None, department_id: int | None = None) -> tuple[list[Service], int]:
        query = self.db.query(Service).filter(Service.is_published.is_(True))
        if search:
            query = query.filter(Service.name.ilike(f"%{search}%"))
        if department_id is not None:
            query = query.filter(Service.department_id == department_id)
        total = query.count()
        items = query.order_by(Service.id).offset(offset).limit(limit).all()
        return items, total

    def list_all(self, offset: int, limit: int) -> tuple[list[Service], int]:
        query = self.db.query(Service)
        total = query.count()
        items = query.order_by(Service.id).offset(offset).limit(limit).all()
        return items, total

    def published_without_chunks(self) -> list[int]:
        rows = self.db.query(Service.id).filter(
            Service.is_published.is_(True),
            ~Service.content_chunks.any(),
        ).all()
        return [service_id for service_id, in rows]
