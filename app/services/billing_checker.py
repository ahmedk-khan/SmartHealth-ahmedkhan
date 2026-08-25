from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Appointment, Billing, BillingStatus
from app.repositories.appointments import AppointmentRepository
from app.core.settings import settings


class BillingChecker:
    def __init__(self, db: Session) -> None:
        self.db = db

    def precheck(self, appointment: Appointment, idempotency_key: str | None = None, *, force_failure: bool | None = None) -> Billing:
        existing = AppointmentRepository(self.db).get_billing_by_appointment_id(appointment.id)
        if existing:
            return existing
        amount = appointment.service.price
        if amount is None:
            raise AppError("Appointment service price is unavailable", status_code=422, error_type="service_price_unavailable")
        if force_failure is None:
            force_failure = settings.billing_force_failure
        if force_failure:
            billing = Billing(appointment_id=appointment.id, amount=amount, status=BillingStatus.DECLINED)
            self.db.add(billing)
            self.db.commit()
            raise AppError("Billing pre-check declined", status_code=402, error_type="billing_declined")
        billing = Billing(appointment_id=appointment.id, amount=amount, status=BillingStatus.APPROVED)
        self.db.add(billing)
        self.db.commit()
        self.db.refresh(billing)
        return billing