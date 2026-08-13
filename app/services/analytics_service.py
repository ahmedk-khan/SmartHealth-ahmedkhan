import datetime

from sqlalchemy import func

from app.core.exceptions import AppError
from app.models import Appointment, Billing, Patient
from app.services.base import BaseService


class AnalyticsService(BaseService):
    def rollup_daily_metrics(self, day: str | None = None) -> dict[str, object]:
        try:
            target_day = datetime.date.fromisoformat(day) if day else datetime.date.today()
        except ValueError as exc:
            raise AppError("Invalid date format", status_code=400, error_type="validation_error", detail=str(exc)) from exc

        start = datetime.datetime.combine(target_day, datetime.time.min, tzinfo=datetime.timezone.utc)
        end = start + datetime.timedelta(days=1)

        total_appointments = self.db.query(func.count(Appointment.id)).filter(
            Appointment.created_at >= start,
            Appointment.created_at < end,
        ).scalar() or 0

        total_patients = self.db.query(func.count(Patient.id)).scalar() or 0
        total_billing = self.db.query(func.coalesce(func.sum(Billing.amount), 0)).scalar() or 0

        return {
            "date": target_day.isoformat(),
            "appointments_total": int(total_appointments),
            "patients_total": int(total_patients),
            "billing_total": float(total_billing),
        }
