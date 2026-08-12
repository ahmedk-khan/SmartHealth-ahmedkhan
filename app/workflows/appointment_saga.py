import datetime
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from sqlalchemy.orm import Session

from app import db as db_module
from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, BillingStatus, Patient, Slot, SlotStatus


@activity.defn
async def validate_appointment_data(appointment_data: dict[str, Any]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == appointment_data["patient_id"]).first()
        if not patient:
            raise ValueError("Patient not found")

        slot = db.query(Slot).filter(Slot.id == appointment_data["slot_id"]).first()
        if not slot:
            raise ValueError("Slot not found")
        if slot.status != SlotStatus.AVAILABLE:
            raise ValueError("Slot is no longer available")

        return {"patient_id": patient.id, "slot_id": slot.id, "provider_id": slot.provider_id, "service_id": slot.service_id}
    finally:
        db.close()


@activity.defn
async def reserve_slot(appointment_data: dict[str, Any]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        slot = db.query(Slot).filter(Slot.id == appointment_data["slot_id"]).first()
        if not slot:
            raise ValueError("Slot not found")
        if slot.status != SlotStatus.AVAILABLE:
            raise ValueError("Slot is no longer available")

        slot.status = SlotStatus.RESERVED
        slot.patient_id = appointment_data["patient_id"]
        slot.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        return {"slot_id": slot.id, "patient_id": slot.patient_id}
    finally:
        db.close()


@activity.defn
async def run_billing_precheck(appointment_data: dict[str, Any]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        existing = db.query(Billing).filter(Billing.appointment_id == appointment_data["appointment_id"]).first()
        if existing:
            return {"status": existing.status.value, "amount": float(existing.amount)}

        billing = Billing(appointment_id=appointment_data["appointment_id"], amount=50.0, status=BillingStatus.APPROVED)
        db.add(billing)
        db.commit()
        return {"status": billing.status.value, "amount": float(billing.amount)}
    finally:
        db.close()


@activity.defn
async def send_reminder(appointment_data: dict[str, Any]) -> dict[str, Any]:
    return {"sent": True, "appointment_id": appointment_data["appointment_id"]}


@activity.defn
async def confirm_appointment(appointment_data: dict[str, Any]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        appointment = db.query(Appointment).filter(Appointment.id == appointment_data["appointment_id"]).first()
        if not appointment:
            raise ValueError("Appointment not found")
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        db.commit()
        return {"status": appointment.status.value}
    finally:
        db.close()


@activity.defn
async def release_slot(appointment_data: dict[str, Any]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        slot = db.query(Slot).filter(Slot.id == appointment_data["slot_id"]).first()
        if slot:
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
        return {"slot_released": True}
    finally:
        db.close()


class AppointmentSagaWorkflow:
    @workflow.run
    async def run(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        validated = await workflow.execute_activity(
            validate_appointment_data,
            appointment_data,
            start_to_close_timeout=timedelta(seconds=30),
        )
        await workflow.execute_activity(
            reserve_slot,
            {**appointment_data, **validated},
            start_to_close_timeout=timedelta(seconds=30),
        )

        db: Session = db_module.SessionLocal()
        try:
            appointment = Appointment(
                patient_id=validated["patient_id"],
                provider_id=validated["provider_id"],
                service_id=validated["service_id"],
                slot_id=validated["slot_id"],
                status=AppointmentStatus.PENDING,
            )
            db.add(appointment)
            db.flush()
            db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
            db.commit()
            db.refresh(appointment)
            appointment_id = appointment.id
        finally:
            db.close()

        try:
            await workflow.execute_activity(
                run_billing_precheck,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
            )
            await workflow.execute_activity(
                send_reminder,
                {"appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
            )
            await workflow.execute_activity(
                confirm_appointment,
                {"appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {"workflow_status": "CONFIRMED", "appointment_id": appointment_id}
        except Exception:
            await workflow.execute_activity(
                release_slot,
                {"slot_id": validated["slot_id"]},
                start_to_close_timeout=timedelta(seconds=30),
            )
            raise


async def _run_appointment_saga_locally(appointment_data: dict[str, Any]) -> dict[str, Any]:
    validated = await validate_appointment_data(appointment_data)
    await reserve_slot({**appointment_data, **validated})

    db: Session = db_module.SessionLocal()
    try:
        if appointment_data.get("force_failure"):
            raise RuntimeError("Simulated saga failure")

        appointment = Appointment(
            patient_id=validated["patient_id"],
            provider_id=validated["provider_id"],
            service_id=validated["service_id"],
            slot_id=validated["slot_id"],
            status=AppointmentStatus.PENDING,
        )
        db.add(appointment)
        db.flush()
        db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        db.commit()
        db.refresh(appointment)
        appointment_id = appointment.id
    except Exception:
        await release_slot({"slot_id": validated["slot_id"]})
        raise
    finally:
        db.close()

    try:
        await run_billing_precheck({**appointment_data, "appointment_id": appointment_id})
        await send_reminder({"appointment_id": appointment_id})
        await confirm_appointment({"appointment_id": appointment_id})
        return {"workflow_status": "CONFIRMED", "appointment_id": appointment_id}
    except Exception:
        await release_slot({"slot_id": validated["slot_id"]})
        raise


async def run_appointment_saga(appointment_data: dict[str, Any]) -> dict[str, Any]:
    try:
        return await AppointmentSagaWorkflow().run(appointment_data)
    except Exception:
        return await _run_appointment_saga_locally(appointment_data)
