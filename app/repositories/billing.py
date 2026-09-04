from decimal import Decimal
from uuid import uuid4

from app.models import Billing
from app.repositories.base import BaseRepository
from app.schemas.billing import ChargeResult


class BillingRepository(BaseRepository):
    def add_and_refresh(self, billing: Billing) -> Billing:
        self.add(billing)
        self.commit()
        self.refresh(billing)
        return billing

    def add_and_commit(self, billing: Billing) -> None:
        self.add(billing)
        self.commit()

    # Async payment provider boundary methods (consolidated from billing_repo.py)
    async def create_charge(self, user_id: int, amount: Decimal) -> ChargeResult:
        """Create a charge for the user (payment provider boundary)."""
        # TODO: replace with the payment provider and persist its charge ID.
        return ChargeResult(charge_id=f"pending-{uuid4()}", user_id=user_id, amount=amount, status="AUTHORIZED")

    async def refund_charge(self, charge_id: str) -> ChargeResult:
        """Refund a charge (payment provider boundary)."""
        # TODO: call the payment provider refund API and persist the result.
        return ChargeResult(charge_id=charge_id, user_id=0, amount=Decimal("0"), status="REFUNDED")
