from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Billing, BillingStatus


class BillingChecker:
    def __init__(self, db: Session) -> None:
        self.db = db

    def precheck(self, appointment_id: int, *, force_failure: bool = False) -> Billing:
        if force_failure:
            billing = Billing(appointment_id=appointment_id, amount=50.0, status=BillingStatus.DECLINED)
            self.db.add(billing)
            self.db.commit()
            raise AppError("Billing pre-check declined", status_code=402, error_type="billing_declined")
        billing = Billing(appointment_id=appointment_id, amount=50.0, status=BillingStatus.APPROVED)
        self.db.add(billing)
        self.db.commit()
        self.db.refresh(billing)
        return billing