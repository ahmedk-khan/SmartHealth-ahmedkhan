"""Temporal workflow definitions for appointment booking and reference demos."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.workers.temporal.policies import (
        BUSINESS_ACTIVITY_RETRY,
        COMPENSATION_RETRY,
        TRANSIENT_ACTIVITY_RETRY,
    )
    from app.workers.temporal.activities.appointment_saga import (
        cancel_pending_appointment,
        cancel_reminder,
        confirm_appointment,
        create_pending_appointment,
        mark_slot_reserved,
        publish_appointment_created_event,
        release_slot,
        reserve_slot,
        run_billing_precheck,
        send_reminder,
        validate_appointment_data,
    )
    from app.workers.temporal.activities.billing_activities import charge_activity, refund_activity
    from app.workers.temporal.activities.notification_activities import send_confirmation_activity
    from app.workers.temporal.activities.scheduling_activities import (
        release_slot_activity,
        reserve_slot_activity,
        validate_slot_activity,
    )
    from app.workers.temporal.contracts import ChargeInput, ConfirmationInput, ReservationInput


@workflow.defn
class AppointmentReservationSagaWorkflow:
    """Reference workflow demonstrating charge + confirmation with typed activity contracts.

    This is not used by the production booking API. It exists as a teaching/reference
    implementation for thin scheduling and billing activities.
    """

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        slot_id = int(input["slot_id"])
        patient_id = int(input.get("patient_id") or input["user_id"])
        appointment_id = int(input["appointment_id"])
        amount = input["amount"]

        await workflow.execute_activity(
            validate_slot_activity,
            slot_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=BUSINESS_ACTIVITY_RETRY,
        )

        await workflow.execute_activity(
            reserve_slot_activity,
            ReservationInput(slot_id=slot_id, patient_id=patient_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=BUSINESS_ACTIVITY_RETRY,
        )

        charge = None
        try:
            charge = await workflow.execute_activity(
                charge_activity,
                ChargeInput(user_id=patient_id, amount=amount),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
        except Exception:
            await workflow.execute_activity(
                release_slot_activity,
                slot_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMPENSATION_RETRY,
            )
            raise

        try:
            confirmation = await workflow.execute_activity(
                send_confirmation_activity,
                ConfirmationInput(user_id=patient_id, appointment_id=appointment_id),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
        except Exception:
            confirmation = {"status": "NOTIFICATION_FAILED"}

        return {
            "status": "CONFIRMED",
            "slot_id": slot_id,
            "charge_id": charge.charge_id,
            "confirmation": confirmation,
        }


@workflow.defn
class AppointmentSagaWorkflow:
    """Production appointment booking saga used by the API."""

    @workflow.run
    async def run(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        demo_pause_seconds = float(appointment_data.get("demo_pause_seconds") or 0)
        if demo_pause_seconds > 0:
            await workflow.sleep(demo_pause_seconds)

        reminder: dict[str, Any] | None = None
        validated: dict[str, Any]

        try:
            validated = await workflow.execute_activity(
                validate_appointment_data,
                appointment_data,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
            await workflow.execute_activity(
                reserve_slot,
                {**appointment_data, **validated},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
            if appointment_data.get("force_failure"):
                await workflow.execute_activity(
                    release_slot,
                    {**appointment_data, **validated},
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=COMPENSATION_RETRY,
                )
                raise RuntimeError("Simulated saga failure")
        except Exception:
            if appointment_data.get("appointment_id"):
                await workflow.execute_activity(
                    cancel_pending_appointment,
                    appointment_data,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=COMPENSATION_RETRY,
                )
            raise

        created = await workflow.execute_activity(
            create_pending_appointment,
            {**appointment_data, **validated},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TRANSIENT_ACTIVITY_RETRY,
        )
        appointment_id = created["appointment_id"]
        await workflow.execute_activity(
            mark_slot_reserved,
            {**appointment_data, "appointment_id": appointment_id},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TRANSIENT_ACTIVITY_RETRY,
        )

        try:
            await workflow.execute_activity(
                run_billing_precheck,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
            reminder = await workflow.execute_activity(
                send_reminder,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            await workflow.execute_activity(
                confirm_appointment,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            event_result = await workflow.execute_activity(
                publish_appointment_created_event,
                {
                    **appointment_data,
                    "appointment_id": appointment_id,
                    **validated,
                    "status": "CONFIRMED",
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            if event_result.get("status") == "delivery_failed":
                workflow.logger.warning(
                    "Appointment confirmed; event queued in outbox after Kafka delivery failure",
                    extra={"appointment_id": appointment_id},
                )
            return {"workflow_status": "CONFIRMED", "appointment_id": appointment_id}
        except Exception:
            workflow.logger.error(
                "Appointment saga failed, running compensation",
                extra={"appointment_id": appointment_id},
            )
            await workflow.execute_activity(
                cancel_reminder,
                {
                    **appointment_data,
                    "appointment_id": appointment_id,
                    "notification_id": reminder.get("notification_id") if reminder else None,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMPENSATION_RETRY,
            )
            await workflow.execute_activity(
                release_slot,
                {
                    **appointment_data,
                    "appointment_id": appointment_id,
                    "slot_id": validated["slot_id"],
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMPENSATION_RETRY,
            )
            await workflow.execute_activity(
                cancel_pending_appointment,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMPENSATION_RETRY,
            )
            raise
