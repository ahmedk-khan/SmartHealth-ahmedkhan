from app.models import Provider, Slot
from app.models.service import Service, provider_services
from app.repositories.base import BaseRepository


class ProviderRepository(BaseRepository):
    def create_seed_provider(self, user_id: int, department_id: int, bio: str) -> Provider:
        """Create and refresh a seed provider without adding audit records."""
        provider = Provider(user_id=user_id, department_id=department_id, bio=bio)
        self.add(provider)
        self.commit()
        self.refresh(provider)
        return provider

    def update_profile(self, provider: Provider, data: dict) -> Provider:
        for field in ("bio", "specialty", "department_id"):
            if field in data:
                setattr(provider, field, data[field])
        self.save_and_refresh(provider)
        return provider

    def get_by_user_id(self, user_id: int) -> Provider | None:
        return self.db.query(Provider).filter(Provider.user_id == user_id).first()

    def get_or_create_for_user(self, user_id: int) -> Provider:
        provider = self.get_by_user_id(user_id)
        if not provider:
            provider = Provider(user_id=user_id)
            self.add(provider)
            self.flush()
        return provider

    def has_service(self, provider_id: int, service_id: int) -> bool:
        return self.db.query(provider_services).filter(
            provider_services.c.provider_id == provider_id,
            provider_services.c.service_id == service_id,
        ).first() is not None

    def link_service_and_commit(self, provider: Provider, service_id: int) -> None:
        self.db.execute(provider_services.insert().values(provider_id=provider.id, service_id=service_id))
        self.commit()

    def get_by_id(self, provider_id: int) -> Provider | None:
        return self.db.query(Provider).filter(Provider.id == provider_id).first()

    def create_provider(self, user_id: int, bio: str | None, department_id: int | None, specialty: str | None = None) -> Provider:
        provider = Provider(user_id=user_id, bio=bio, department_id=department_id, specialty=specialty)
        self.add(provider)
        self.flush()
        self.audit("provider", provider.id, "created", actor_user_id=user_id, after={"department_id": department_id, "specialty": specialty})
        self.commit()
        self.refresh(provider)
        return provider

    def list_providers(self, offset: int, limit: int) -> tuple[list[Provider], int]:
        query = self.db.query(Provider)
        total = query.count()
        items = query.order_by(Provider.id).offset(offset).limit(limit).all()
        return items, total

    def list_slots(self, provider_id: int, offset: int, limit: int) -> tuple[list[Slot], int]:
        query = self.db.query(Slot).filter(Slot.provider_id == provider_id)
        total = query.count()
        items = query.order_by(Slot.start_datetime).offset(offset).limit(limit).all()
        return items, total

    def list_services(self, provider_id: int, offset: int, limit: int) -> tuple[list[Service], int]:
        query = (
            self.db.query(Service)
            .join(provider_services, provider_services.c.service_id == Service.id)
            .filter(provider_services.c.provider_id == provider_id)
        )
        total = query.distinct(Service.id).count()
        items = query.distinct(Service.id).order_by(Service.id).offset(offset).limit(limit).all()
        return items, total
