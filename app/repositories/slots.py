import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Patient, Provider, Service, Slot, SlotStatus
from app.repositories.base import BaseRepository


class SlotRepository(BaseRepository):
    def get_by_provider_and_service(self, provider_id: int, service_id: int) -> Slot | None:
        """Return the first slot for a provider and service pair."""
        return self.db.query(Slot).filter(Slot.provider_id == provider_id, Slot.service_id == service_id).first()

    def create_seed_slot(self, data: dict) -> Slot:
        """Create and commit a seed slot without adding audit records."""
        slot = Slot(**data)
        self.add(slot)
        self.commit()
        return slot

    def update_slot(self, slot: Slot, data: dict) -> Slot:
        for field in ("service_id", "start_datetime", "end_datetime"):
            if field in data:
                setattr(slot, field, data[field])
        self.save_and_refresh(slot)
        return slot

    def delete_slot(self, slot: Slot) -> None:
        self.delete(slot)

    def get_by_id(self, slot_id: int) -> Slot | None:
        return self.db.query(Slot).filter(Slot.id == slot_id).first()

    def create_slot(self, data: dict) -> Slot:
        slot = Slot(**data)
        self.add(slot)
        self.flush()
        self.audit("slot", slot.id, "created", after={"status": slot.status.value, "provider_id": slot.provider_id, "service_id": slot.service_id})
        self.commit()
        self.refresh(slot)
        return slot

    def release_expired_reservations(self, ttl_minutes: int) -> int:
        """Release RESERVED slots that exceeded the hold TTL and have no appointment."""
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=ttl_minutes)
        expired_slots = (
            self.db.query(Slot)
            .outerjoin(Appointment, Appointment.slot_id == Slot.id)
            .filter(
                Slot.status == SlotStatus.RESERVED,
                Slot.updated_at < cutoff,
                Appointment.id.is_(None),
            )
            .all()
        )
        released = 0
        for slot in expired_slots:
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = datetime.datetime.now(datetime.timezone.utc)
            released += 1
        if released:
            self.commit()
        return released

    def reserve_for_patient(self, slot_id: int, patient_id: int, *, ttl_minutes: int | None = None) -> Slot | None:
        if ttl_minutes is not None:
            self.release_expired_reservations(ttl_minutes)
        now = datetime.datetime.now(datetime.timezone.utc)
        updated = self.db.query(Slot).filter(Slot.id == slot_id, Slot.status == SlotStatus.AVAILABLE).update(
            {"status": SlotStatus.RESERVED, "patient_id": patient_id, "updated_at": now},
            synchronize_session=False,
        )
        if updated != 1:
            return None
        self.commit()
        return self.get_by_id(slot_id)

    def list_slots(self, offset: int, limit: int, patient_only_available: bool = False) -> tuple[list[Slot], int]:
        query = self.db.query(Slot)
        if patient_only_available:
            query = query.filter(Slot.status == SlotStatus.AVAILABLE)
        total = query.count()
        items = query.order_by(Slot.start_datetime).offset(offset).limit(limit).all()
        return items, total

    def list_by_provider(
        self,
        provider_id: int,
        offset: int,
        limit: int,
        available_only: bool = False,
    ) -> tuple[list[Slot], int]:
        """Return all slots for a given provider, optionally filtered to AVAILABLE only."""
        query = self.db.query(Slot).filter(Slot.provider_id == provider_id)
        if available_only:
            query = query.filter(Slot.status == SlotStatus.AVAILABLE)
        total = query.count()
        items = query.order_by(Slot.start_datetime).offset(offset).limit(limit).all()
        return items, total

    def list_by_service(
        self,
        service_id: int,
        offset: int,
        limit: int,
        available_only: bool = False,
    ) -> tuple[list[Slot], int]:
        """Return all slots for a given service, optionally filtered to AVAILABLE only."""
        query = self.db.query(Slot).filter(Slot.service_id == service_id)
        if available_only:
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


class SchedulingRepository:
    """Async repository for workflow-specific slot scheduling operations (consolidated from scheduling_repo.py)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_slot(self, slot_id: int) -> Slot | None:
        return await self.session.scalar(select(Slot).where(Slot.id == slot_id))

    async def reserve_slot(self, slot_id: int, patient_id: int) -> Slot | None:
        result = await self.session.execute(
            update(Slot).where(Slot.id == slot_id, Slot.status == SlotStatus.AVAILABLE)
            .values(status=SlotStatus.RESERVED, patient_id=patient_id)
        )
        if result.rowcount != 1:
            await self.session.rollback()
            return None
        await self.session.commit()
        return await self.get_slot(slot_id)

    async def release_slot(self, slot_id: int) -> Slot | None:
        result = await self.session.execute(
            update(Slot).where(Slot.id == slot_id, Slot.status == SlotStatus.RESERVED)
            .values(status=SlotStatus.AVAILABLE, patient_id=None)
        )
        if result.rowcount != 1:
            await self.session.rollback()
            return None
        await self.session.commit()
        return await self.get_slot(slot_id)
