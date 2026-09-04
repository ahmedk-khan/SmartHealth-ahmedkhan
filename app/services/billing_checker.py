from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError, ValidationError
from app.models import Appointment, Billing, BillingStatus
from app.repositories.appointments import AppointmentRepository
from app.repositories.billing import BillingRepository
from app.core.settings import settings


class BillingChecker:
    def __init__(self, db: Session | AsyncSession) -> None:
        self.db = db
        self.billing = BillingRepository(db) if isinstance(db, Session) else BillingRepository(db)

    def precheck(self, appointment: Appointment, idempotency_key: str | None = None, *, force_failure: bool | None = None) -> Billing:
        existing = AppointmentRepository(self.db).get_billing_by_appointment_id(appointment.id)
        if existing:
            return existing
        amount = appointment.service.price
        if amount is None:
            raise AppError("Appointment service price is unavailable", status_code=422, error_type="service_price_unavailable", code="SERVICE_PRICE_UNAVAILABLE")
        if force_failure is None:
            force_failure = settings.billing_force_failure
        if force_failure:
            billing = Billing(appointment_id=appointment.id, amount=amount, status=BillingStatus.DECLINED)
            self.billing.add_and_commit(billing)
            raise ConflictError("Billing pre-check declined", code="BILLING_PRECHECK_DECLINED")
        billing = Billing(appointment_id=appointment.id, amount=amount, status=BillingStatus.APPROVED)
        return self.billing.add_and_refresh(billing)

    # Async methods for Temporal activities (consolidated from workers/temporal/services/billing_service.py)
    async def charge(self, user_id: int, amount: Decimal) -> dict[str, str | int | Decimal]:
        """Charge user for appointment (payment provider boundary)."""
        if user_id <= 0 or amount < 0:
            raise ValidationError("Invalid billing input")
        result = await self.billing.create_charge(user_id, amount)
        return {"charge_id": result.charge_id, "user_id": result.user_id, "amount": result.amount, "status": result.status}

    async def refund(self, charge_id: str) -> dict[str, str | int | Decimal]:
        """Refund a charge (payment provider boundary)."""
        if not charge_id:
            raise ValidationError("Charge ID is required")
        result = await self.billing.refund_charge(charge_id)
        return {"charge_id": result.charge_id, "user_id": result.user_id, "amount": result.amount, "status": result.status}
