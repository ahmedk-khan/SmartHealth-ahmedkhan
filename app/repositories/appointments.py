import datetime

from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, Service, Slot, SlotStatus, Visit, VisitStatus, WaitlistEntry, WaitlistStatus
from app.repositories.base import BaseRepository


class AppointmentRepository(BaseRepository):
    def create_requested(self, data: dict) -> Appointment:
        """Create and commit a requested appointment with its history and audit record."""
        from app.models.audit import AuditLog

        appointment = Appointment(
            patient_id=data["patient_id"],
            provider_id=data["provider_id"],
            service_id=data["service_id"],
            slot_id=data["slot_id"],
            status=AppointmentStatus.REQUESTED,
            booking_key=data.get("idempotency_key"),
        )
        self.add(appointment)
        self.flush()
        self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        self.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="requested", after={"status": appointment.status.value}))
        self.commit()
        self.refresh(appointment)
        return appointment

    def mark_slot_reserved(self, appointment_id: int) -> Appointment | None:
        """Mark a requested appointment as slot-reserved and commit its audit history."""
        from app.models.audit import AuditLog

        appointment = self.get_by_id(appointment_id)
        if not appointment:
            return None
        if appointment.status == AppointmentStatus.REQUESTED:
            appointment.status = AppointmentStatus.SLOT_RESERVED
            appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
            self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
            self.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="slot_reserved", after={"status": appointment.status.value}))
            self.commit()
        return appointment

    def confirm(self, appointment_id: int) -> Appointment | None:
        """Confirm an appointment and commit its status history and audit record."""
        from app.models.audit import AuditLog

        appointment = self.get_by_id(appointment_id)
        if not appointment:
            return None
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        self.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="confirmed", after={"status": appointment.status.value}))
        self.commit()
        return appointment

    def release_slot_for_appointment(self, slot_id: int, appointment_id: int | None = None) -> tuple[dict[str, object], int | None]:
        """Release a slot unless it belongs to another appointment patient."""
        slot = self.db.query(Slot).filter(Slot.id == slot_id).first()
        if slot:
            if appointment_id is not None:
                appointment = self.get_by_id(appointment_id)
                if appointment and slot.patient_id != appointment.patient_id:
                    return {"slot_released": False, "reason": "slot_owned_by_another_patient"}, None
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = datetime.datetime.now(datetime.timezone.utc)
            self.commit()
        return {"slot_released": True}, slot.id if slot else None

    def cancel_pending(self, appointment_id: int) -> bool:
        """Cancel a pending appointment and commit its compensation history."""
        from app.models.audit import AuditLog

        appointment = self.get_by_id(appointment_id)
        if appointment and appointment.status in {
            AppointmentStatus.REQUESTED,
            AppointmentStatus.SLOT_RESERVED,
            AppointmentStatus.PENDING,
            AppointmentStatus.CONFIRMED,
        }:
            appointment.status = AppointmentStatus.CANCELLED
            appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
            self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
            self.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="compensated", after={"status": appointment.status.value}))
            self.commit()
        return appointment is not None

    def list_due_confirmed_reminders(self, now: datetime.datetime, window_end: datetime.datetime, limit: int = 100) -> list[Appointment]:
        """Return confirmed appointments whose slots fall within the reminder window."""
        return self.db.query(Appointment).join(Slot).filter(
            Appointment.status == AppointmentStatus.CONFIRMED,
            Slot.start_datetime >= now,
            Slot.start_datetime <= window_end,
        ).limit(limit).all()

    def iter_due_confirmed_reminders(self, now: datetime.datetime, window_end: datetime.datetime, batch_size: int = 100):
        """Yield confirmed appointments in bounded batches within the reminder window."""
        return self.db.query(Appointment).join(Slot).filter(
            Appointment.status == AppointmentStatus.CONFIRMED,
            Slot.start_datetime >= now,
            Slot.start_datetime <= window_end,
        ).yield_per(batch_size)

    def get_one_or_none_by_id(self, appointment_id: int) -> Appointment | None:
        """Return one appointment by ID or None when no appointment exists."""
        return self.db.query(Appointment).filter(Appointment.id == appointment_id).one_or_none()

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
        self.add(appointment)
        self.flush()
        self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        self.commit()
        self.refresh(appointment)
        return appointment

    def add_status_history(self, appointment_id: int, status: AppointmentStatus) -> None:
        self.add(AppointmentStatusHistory(appointment_id=appointment_id, status=status))

    def cancel(self, appointment: Appointment) -> Appointment:
        previous_status = appointment.status.value
        appointment.status = AppointmentStatus.CANCELLED
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
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
                self.add(promoted_appointment)
                self.flush()
                self.add(AppointmentStatusHistory(
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
        self.commit()
        self.refresh(appointment)
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
        self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        self.audit("appointment", appointment.id, "rescheduled", before={"slot_id": old_slot.id if old_slot else None}, after={"slot_id": new_slot.id})
        self.commit()
        self.refresh(appointment)
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
            self.add(visit)
        else:
            visit.status = target_status
        if target_status == VisitStatus.CHECKED_IN and visit.checked_in_at is None:
            visit.checked_in_at = now
        if target_status == VisitStatus.COMPLETED and visit.completed_at is None:
            visit.completed_at = now
        self.add(AppointmentStatusHistory(
            appointment_id=appointment.id,
            status=appointment.status,
            from_status=appointment.visit_status,
            to_status=target_status,
            actor=actor,
            reason=reason,
        ))
        self.commit()
        return self.get_by_id(appointment.id)

    def mark_no_show(self, appointment: Appointment) -> Appointment:
        now = datetime.datetime.now(datetime.timezone.utc)
        appointment.status = AppointmentStatus.NO_SHOW
        appointment.updated_at = now
        self.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        slot = self.db.query(Slot).filter(Slot.id == appointment.slot_id).first()
        if slot:
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = now
        self.commit()
        return self.get_by_id(appointment.id)

    def create_billing(self, appointment_id: int, amount: float = 50.0) -> Billing:
        billing = Billing(appointment_id=appointment_id, amount=amount)
        self.save_and_refresh(billing)
        return billing

    def get_billing_by_appointment_id(self, appointment_id: int) -> Billing | None:
        return self.db.query(Billing).filter(Billing.appointment_id == appointment_id).first()

    def get_service_price_for_appointment(self, appointment_id: int):
        return self.db.query(Service.price).join(
            Appointment, Appointment.service_id == Service.id
        ).filter(Appointment.id == appointment_id).scalar()
