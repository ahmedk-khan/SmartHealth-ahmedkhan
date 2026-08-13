import datetime

from sqlalchemy.orm import Session

from app.models import Patient, Provider, Service, Slot, SlotStatus
from app.repositories.base import BaseRepository


class SlotRepository(BaseRepository):
    def get_by_id(self, slot_id: int) -> Slot | None:
        return self.db.query(Slot).filter(Slot.id == slot_id).first()

    def create_slot(self, data: dict) -> Slot:
        slot = Slot(**data)
        self.db.add(slot)
        self.db.commit()
        self.db.refresh(slot)
        return slot

    def reserve_for_patient(self, slot_id: int, patient_id: int) -> Slot | None:
        now = datetime.datetime.now(datetime.timezone.utc)
        updated = self.db.query(Slot).filter(Slot.id == slot_id, Slot.status == SlotStatus.AVAILABLE).update(
            {"status": SlotStatus.RESERVED, "patient_id": patient_id, "updated_at": now},
            synchronize_session=False,
        )
        if updated != 1:
            return None
        self.db.commit()
        return self.get_by_id(slot_id)

    def list_slots(self, offset: int, limit: int, patient_only_available: bool = False) -> tuple[list[Slot], int]:
        query = self.db.query(Slot)
        if patient_only_available:
            query = query.filter(Slot.status == SlotStatus.AVAILABLE)
        total = query.count()
        items = query.order_by(Slot.start_datetime).offset(offset).limit(limit).all()
        return items, total

    def validate_provider_and_service(self, provider_id: int, service_id: int) -> bool:
        provider = self.db.query(Provider).filter(Provider.id == provider_id).first()
        service = self.db.query(Service).filter(Service.id == service_id).first()
        return provider is not None and service is not None

    def get_patient_by_user_id(self, user_id: int) -> Patient | None:
        return self.db.query(Patient).filter(Patient.user_id == user_id).first()