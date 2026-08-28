from sqlalchemy.orm import Session

from app.core.exceptions import app_error, conflict_error
from app.models import Appointment, Billing, BillingStatus
from app.repositories.appointments import AppointmentRepository
from app.repositories.billing import BillingRepository
from app.core.settings import settings


class BillingChecker:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.billing = BillingRepository(db)

    def precheck(self, appointment: Appointment, idempotency_key: str | None = None, *, force_failure: bool | None = None) -> Billing:
        existing = AppointmentRepository(self.db).get_billing_by_appointment_id(appointment.id)
        if existing:
            return existing
        amount = appointment.service.price
        if amount is None:
            raise app_error("Appointment service price is unavailable", status_code=422, error_type="service_price_unavailable")
        if force_failure is None:
            force_failure = settings.billing_force_failure
        if force_failure:
            billing = Billing(appointment_id=appointment.id, amount=amount, status=BillingStatus.DECLINED)
            self.billing.add_and_commit(billing)
            raise conflict_error("Billing pre-check declined")
        billing = Billing(appointment_id=appointment.id, amount=amount, status=BillingStatus.APPROVED)
        return self.billing.add_and_refresh(billing)
