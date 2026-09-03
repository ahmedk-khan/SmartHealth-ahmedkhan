"""Thin Temporal adapters for scheduling operations.

Activities validate and map serialized input, call one service method, and map
the result. They must not contain ORM access, business rules, or orchestration.
"""

from temporalio import activity

from app.db.async_session import get_session
from app.workers.temporal.contracts import ReservationInput, ReservationResult
from app.repositories.slots import SchedulingRepository
from app.services.slot_service import SlotService


@activity.defn
async def validate_slot_activity(slot_id: int) -> dict[str, int | str]:
    if slot_id <= 0:
        raise ValueError("slot_id must be positive")
    async with get_session() as session:
        scheduling_repo = SchedulingRepository(session)
        result = await SlotService(session).validate_slot_async(scheduling_repo, slot_id)
    return result


@activity.defn
async def reserve_slot_activity(input: ReservationInput) -> ReservationResult:
    if input.slot_id <= 0 or input.patient_id <= 0:
        raise ValueError("slot_id and patient_id must be positive")
    async with get_session() as session:
        scheduling_repo = SchedulingRepository(session)
        result = await SlotService(session).reserve_slot_async(
            scheduling_repo,
            input.slot_id,
            input.patient_id,
        )
    return ReservationResult(result.get("slot_id"), result.get("patient_id"), result.get("status"))


@activity.defn
async def release_slot_activity(slot_id: int) -> ReservationResult:
    if slot_id <= 0:
        raise ValueError("slot_id must be positive")
    async with get_session() as session:
        scheduling_repo = SchedulingRepository(session)
        result = await SlotService(session).release_slot_async(scheduling_repo, slot_id)
    return ReservationResult(result.get("slot_id"), result.get("user_id"), result.get("status"))
