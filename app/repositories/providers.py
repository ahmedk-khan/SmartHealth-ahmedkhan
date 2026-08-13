from sqlalchemy.orm import Session

from app.models import Provider, Slot
from app.repositories.base import BaseRepository


class ProviderRepository(BaseRepository):
    def get_by_user_id(self, user_id: int) -> Provider | None:
        return self.db.query(Provider).filter(Provider.user_id == user_id).first()

    def get_by_id(self, provider_id: int) -> Provider | None:
        return self.db.query(Provider).filter(Provider.id == provider_id).first()

    def create_provider(self, user_id: int, bio: str | None, department_id: int | None) -> Provider:
        provider = Provider(user_id=user_id, bio=bio, department_id=department_id)
        self.db.add(provider)
        self.db.commit()
        self.db.refresh(provider)
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