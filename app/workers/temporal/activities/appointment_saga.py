"""Thin Temporal adapters for the appointment booking saga."""

from __future__ import annotations

from typing import Any

from temporalio import activity

from app.core.exceptions import AppError
from app.services.appointment_saga_service import AppointmentSagaService
from app.workers.temporal.activity_errors import to_non_retryable_application_error
from app.workers.temporal.activity_session import activity_session
from app.workers.temporal.logging import log_activity_error, log_activity_step, setup_activity_context


def _run_activity(activity_name: str, appointment_data: dict[str, Any], action):
    setup_activity_context(appointment_data, activity_name)
    try:
        with activity_session() as db:
            return action(AppointmentSagaService(db))
    except AppError as exc:
        log_activity_error(activity_name, exc)
        raise to_non_retryable_application_error(exc) from exc


@activity.defn
async def validate_appointment_data(appointment_data: dict[str, Any]) -> dict[str, Any]:
    def execute(service: AppointmentSagaService) -> dict[str, Any]:
        log_activity_step("Validating booking", {"patient_id": appointment_data.get("patient_id")})
        return service.validate_booking(appointment_data)

    return _run_activity("validate_appointment_data", appointment_data, execute)


@activity.defn
async def reserve_slot(appointment_data: dict[str, Any]) -> dict[str, Any]:
    def execute(service: AppointmentSagaService) -> dict[str, Any]:
        log_activity_step("Reserving slot", {"slot_id": appointment_data.get("slot_id")})
        return service.reserve_slot(appointment_data)

    return _run_activity("reserve_slot", appointment_data, execute)


@activity.defn
async def run_billing_precheck(appointment_data: dict[str, Any]) -> dict[str, Any]:
    def execute(service: AppointmentSagaService) -> dict[str, Any]:
        return service.run_billing_precheck(appointment_data)

    return _run_activity("run_billing_precheck", appointment_data, execute)


@activity.defn
async def create_pending_appointment(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "create_pending_appointment")
    with activity_session() as db:
        return AppointmentSagaService(db).create_pending_appointment(appointment_data)


@activity.defn
async def mark_slot_reserved(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "mark_slot_reserved")
    with activity_session() as db:
        return AppointmentSagaService(db).mark_slot_reserved(appointment_data)


@activity.defn
async def send_reminder(appointment_data: dict[str, Any]) -> dict[str, Any]:
    def execute(service: AppointmentSagaService) -> dict[str, Any]:
        return service.schedule_reminder(appointment_data)

    return _run_activity("send_reminder", appointment_data, execute)


@activity.defn
async def cancel_reminder(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "cancel_reminder")
    with activity_session() as db:
        return AppointmentSagaService(db).cancel_reminder(appointment_data)


@activity.defn
async def confirm_appointment(appointment_data: dict[str, Any]) -> dict[str, Any]:
    def execute(service: AppointmentSagaService) -> dict[str, Any]:
        return service.confirm_appointment(appointment_data)

    return _run_activity("confirm_appointment", appointment_data, execute)


@activity.defn
async def publish_appointment_created_event(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "publish_appointment_created_event")
    with activity_session() as db:
        return await AppointmentSagaService(db).publish_created_event(appointment_data)


@activity.defn
async def release_slot(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "release_slot")
    try:
        with activity_session() as db:
            return AppointmentSagaService(db).release_slot(appointment_data)
    except Exception as exc:
        log_activity_error("release_slot", exc)
        raise


@activity.defn
async def cancel_pending_appointment(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "cancel_pending_appointment")
    with activity_session() as db:
        return AppointmentSagaService(db).cancel_pending_appointment(appointment_data)
