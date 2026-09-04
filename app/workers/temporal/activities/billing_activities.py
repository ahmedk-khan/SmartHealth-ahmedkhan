"""Thin Temporal adapters for billing operations.

No payment gateway, ORM calls, compensation logic, or workflow branching may
be added here. The activity delegates exactly one operation to the service.
"""

from decimal import Decimal

from temporalio import activity

from app.db.async_session import get_session
from app.workers.temporal.contracts import ChargeInput, ChargeResult
from app.repositories.billing import BillingRepository
from app.services.billing_checker import BillingChecker


@activity.defn
async def charge_activity(input: ChargeInput) -> ChargeResult:
    if input.user_id <= 0 or input.amount < 0:
        raise ValueError("Invalid charge input")
    async with get_session() as session:
        result = await BillingChecker(session).charge(input.user_id, Decimal(input.amount))
    return ChargeResult(result.get("charge_id"), result.get("user_id"), result.get("amount"), result.get("status"))


@activity.defn
async def refund_activity(charge_id: str) -> ChargeResult:
    if not charge_id:
        raise ValueError("charge_id is required")
    async with get_session() as session:
        result = await BillingChecker(session).refund(charge_id)
    return ChargeResult(result.get("charge_id"), result.get("user_id"), result.get("amount"), result.get("status"))
