import datetime

from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, Service, Slot, SlotStatus, Visit, VisitStatus, WaitlistEntry, WaitlistStatus
from app.repositories.base import BaseRepository


class AppointmentRepository(BaseRepository):
    def get_by_booking_key(self, booking_key: str) -> Appointment | None:
        return self.db.query(Appointment).filter(Appointment.booking_key == booking_key).first()

    def list_scoped(self, *, patient_id: int | None = None, provider_id: int | None = None, limit: int = 20, offset: int = 0) -> tuple[list[Appointment], int]:
        query = self.db.query(Appointment)
        if patient_id is not None:
            query = query.filter(Appointment.patient_id == patient_id)
        if provider_id is not None:
            query = query.filter(Appointment.provider_id == provider_id)
        total = query.count()
        items = query.order_by(Appointment.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

    def get_by_id(self, appointment_id: int) -> Appointment | None:
        return self.db.query(Appointment).filter(Appointment.id == appointment_id).first()

    def get_by_id_or_none(self, appointment_id: int) -> Appointment | None:
        return self.get_by_id(appointment_id)

    def create_pending(self, patient_id: int, provider_id: int, service_id: int, slot_id: int, booking_key: str | None = None) -> Appointment:
        appointment = Appointment(
            patient_id=patient_id,
            provider_id=provider_id,
            service_id=service_id,
            slot_id=slot_id,
            booking_key=booking_key,
            status=AppointmentStatus.PENDING,
        )
        self.db.add(appointment)
        self.db.flush()
        self.db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def add_status_history(self, appointment_id: int, status: AppointmentStatus) -> None:
        self.db.add(AppointmentStatusHistory(appointment_id=appointment_id, status=status))

    def cancel(self, appointment: Appointment) -> Appointment:
        previous_status = appointment.status.value
        appointment.status = AppointmentStatus.CANCELLED
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        slot = self.db.query(Slot).filter(Slot.id == appointment.slot_id).first()
        if slot:
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = appointment.updated_at
            next_entry = self.db.query(WaitlistEntry).filter(
                WaitlistEntry.slot_id == slot.id,
                WaitlistEntry.status == WaitlistStatus.WAITING,
            ).order_by(WaitlistEntry.created_at, WaitlistEntry.id).first()
            if next_entry:
                slot.status = SlotStatus.RESERVED
                slot.patient_id = next_entry.patient_id
                next_entry.status = WaitlistStatus.PROMOTED
                next_entry.updated_at = appointment.updated_at
                promoted_appointment = Appointment(
                    patient_id=next_entry.patient_id,
                    provider_id=slot.provider_id,
                    service_id=slot.service_id,
                    slot_id=slot.id,
                    status=AppointmentStatus.CONFIRMED,
                    updated_at=appointment.updated_at,
                )
                self.db.add(promoted_appointment)
                self.db.flush()
                self.db.add(AppointmentStatusHistory(
                    appointment_id=promoted_appointment.id,
                    status=promoted_appointment.status,
                ))
                self.audit(
                    "appointment",
                    promoted_appointment.id,
                    "promoted_from_waitlist",
                    after={
                        "status": promoted_appointment.status.value,
                        "slot_id": slot.id,
                        "waitlist_entry_id": next_entry.id,
                    },
                )
            self.audit("appointment", appointment.id, "cancelled", before={"status": previous_status}, after={"status": appointment.status.value})
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def reschedule(self, appointment: Appointment, new_slot: Slot) -> Appointment:
        if new_slot.id == appointment.slot_id:
            return appointment
        now = datetime.datetime.now(datetime.timezone.utc)
        old_slot = self.db.query(Slot).filter(Slot.id == appointment.slot_id).first()
        claimed = self.db.query(Slot).filter(
            Slot.id == new_slot.id,
            Slot.status == SlotStatus.AVAILABLE,
        ).update(
            {"status": SlotStatus.RESERVED, "patient_id": appointment.patient_id, "updated_at": now},
            synchronize_session=False,
        )
        if claimed != 1:
            self.db.rollback()
            raise ValueError("Replacement slot is no longer available")
        if old_slot:
            old_slot.status = SlotStatus.AVAILABLE
            old_slot.patient_id = None
            old_slot.updated_at = now

        appointment.slot_id = new_slot.id
        appointment.provider_id = new_slot.provider_id
        appointment.service_id = new_slot.service_id
        appointment.status = AppointmentStatus.SLOT_RESERVED
        appointment.updated_at = now
        self.db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        self.audit("appointment", appointment.id, "rescheduled", before={"slot_id": old_slot.id if old_slot else None}, after={"slot_id": new_slot.id})
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def transition_visit_status(self, appointment: Appointment, target_status: VisitStatus, *, actor: str, reason: str) -> Appointment:
        now = datetime.datetime.now(datetime.timezone.utc)
        updated = self.db.query(Appointment).filter(
            Appointment.id == appointment.id,
            Appointment.visit_status == appointment.visit_status,
        ).update({"visit_status": target_status, "updated_at": now}, synchronize_session=False)
        if updated != 1:
            self.db.rollback()
            raise ValueError("Visit status changed concurrently")
        visit = self.db.query(Visit).filter(Visit.appointment_id == appointment.id).first()
        if visit is None:
            visit = Visit(appointment_id=appointment.id, status=target_status)
            self.db.add(visit)
        else:
            visit.status = target_status
        if target_status == VisitStatus.CHECKED_IN and visit.checked_in_at is None:
            visit.checked_in_at = now
        if target_status == VisitStatus.COMPLETED and visit.completed_at is None:
            visit.completed_at = now
        self.db.add(AppointmentStatusHistory(
            appointment_id=appointment.id,
            status=appointment.status,
            from_status=appointment.visit_status,
            to_status=target_status,
            actor=actor,
            reason=reason,
        ))
        self.db.commit()
        return self.get_by_id(appointment.id)

    def mark_no_show(self, appointment: Appointment) -> Appointment:
        now = datetime.datetime.now(datetime.timezone.utc)
        appointment.status = AppointmentStatus.NO_SHOW
        appointment.updated_at = now
        self.db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        slot = self.db.query(Slot).filter(Slot.id == appointment.slot_id).first()
        if slot:
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = now
        self.db.commit()
        return self.get_by_id(appointment.id)

    def create_billing(self, appointment_id: int, amount: float = 50.0) -> Billing:
        billing = Billing(appointment_id=appointment_id, amount=amount)
        self.db.add(billing)
        self.db.commit()
        self.db.refresh(billing)
        return billing

    def get_billing_by_appointment_id(self, appointment_id: int) -> Billing | None:
        return self.db.query(Billing).filter(Billing.appointment_id == appointment_id).first()

    def get_service_price_for_appointment(self, appointment_id: int):
        return self.db.query(Service.price).join(
            Appointment, Appointment.service_id == Service.id
        ).filter(Appointment.id == appointment_id).scalar()