import datetime

from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, Slot, SlotStatus, VisitStatus
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
        appointment.status = AppointmentStatus.CANCELLED
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        slot = self.db.query(Slot).filter(Slot.id == appointment.slot_id).first()
        if slot:
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = appointment.updated_at
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def reschedule(self, appointment: Appointment, new_slot: Slot) -> Appointment:
        old_slot = self.db.query(Slot).filter(Slot.id == appointment.slot_id).first()
        if old_slot:
            old_slot.status = SlotStatus.AVAILABLE
            old_slot.patient_id = None
            old_slot.updated_at = datetime.datetime.now(datetime.timezone.utc)

        new_slot.status = SlotStatus.RESERVED
        new_slot.patient_id = appointment.patient_id
        new_slot.updated_at = datetime.datetime.now(datetime.timezone.utc)

        appointment.slot_id = new_slot.id
        appointment.provider_id = new_slot.provider_id
        appointment.service_id = new_slot.service_id
        appointment.status = AppointmentStatus.PENDING
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def transition_visit_status(self, appointment: Appointment, target_status: VisitStatus) -> Appointment:
        appointment.visit_status = target_status
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def create_billing(self, appointment_id: int, amount: float = 50.0) -> Billing:
        billing = Billing(appointment_id=appointment_id, amount=amount)
        self.db.add(billing)
        self.db.commit()
        self.db.refresh(billing)
        return billing

    def get_billing_by_appointment_id(self, appointment_id: int) -> Billing | None:
        return self.db.query(Billing).filter(Billing.appointment_id == appointment_id).first()