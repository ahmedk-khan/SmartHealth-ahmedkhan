import datetime

from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, Slot, SlotStatus, VisitStatus, WaitlistEntry, WaitlistStatus
from app.repositories.base import BaseRepository


class AppointmentRepository(BaseRepository):
    def get_by_id(self, appointment_id: int) -> Appointment | None:
        return self.db.query(Appointment).filter(Appointment.id == appointment_id).first()

    def get_by_id_or_none(self, appointment_id: int) -> Appointment | None:
        return self.get_by_id(appointment_id)

    def create_pending(self, patient_id: int, provider_id: int, service_id: int, slot_id: int) -> Appointment:
        appointment = Appointment(
            patient_id=patient_id,
            provider_id=provider_id,
            service_id=service_id,
            slot_id=slot_id,
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

    def transition_visit_status(self, appointment: Appointment, target_status: VisitStatus) -> Appointment:
        now = datetime.datetime.now(datetime.timezone.utc)
        updated = self.db.query(Appointment).filter(
            Appointment.id == appointment.id,
            Appointment.visit_status == appointment.visit_status,
        ).update({"visit_status": target_status, "updated_at": now}, synchronize_session=False)
        if updated != 1:
            self.db.rollback()
            raise ValueError("Visit status changed concurrently")
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