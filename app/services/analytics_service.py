import datetime

from sqlalchemy import func

from app.core.exceptions import AppError
from app.models import AnalyticsAppointmentDaily, AnalyticsServiceDaily, Appointment, AppointmentStatus, Billing, Patient, Service, VisitStatus
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

    def _aggregate_metric(self, event_type: str, *, visit_status: str | None = None) -> int:
        base_query = self.db.query(func.coalesce(func.sum(AnalyticsAppointmentDaily.total_events), 0))
        if event_type in {"visit.completed", "appointment.visit_status_changed"}:
            base_query = base_query.filter(
                AnalyticsAppointmentDaily.event_type.in_(["visit.completed", "appointment.visit_status_changed"]),
                AnalyticsAppointmentDaily.visit_status == (visit_status or "COMPLETED"),
            )
        else:
            base_query = base_query.filter(AnalyticsAppointmentDaily.event_type == event_type)
        value = base_query.scalar() or 0
        return int(value)

    def _aggregate_service_metric(self, event_type: str) -> int:
        value = (
            self.db.query(func.coalesce(func.sum(AnalyticsServiceDaily.total_events), 0))
            .filter(AnalyticsServiceDaily.event_type == event_type)
            .scalar()
            or 0
        )
        return int(value)

    def get_dashboard_metrics(self) -> dict[str, int | float]:
        appointments_total = self._aggregate_metric("appointment.created")
        cancelled_appointments_total = self._aggregate_metric("appointment.cancelled")
        completed_visits_total = self._aggregate_metric("visit.completed", visit_status="COMPLETED")
        published_services_total = self._aggregate_service_metric("service.published")
        patients_total = (
            self.db.query(func.coalesce(func.count(func.distinct(AnalyticsAppointmentDaily.patient_id)), 0))
            .filter(
                AnalyticsAppointmentDaily.event_type == "appointment.created",
                AnalyticsAppointmentDaily.patient_id.isnot(None),
            )
            .scalar()
            or 0
        )
        billing_total = self.db.query(func.coalesce(func.sum(Billing.amount), 0)).scalar() or 0

        return {
            "appointments_total": int(appointments_total),
            "patients_total": int(patients_total),
            "completed_visits_total": int(completed_visits_total),
            "cancelled_appointments_total": int(cancelled_appointments_total),
            "published_services_total": int(published_services_total),
            "billing_total": float(billing_total),
        }

    def reconcile_metrics(self) -> dict[str, object]:
        aggregate_metrics = self.get_dashboard_metrics()

        raw_metrics = {
            "appointments_total": self.db.query(func.count(Appointment.id)).scalar() or 0,
            "patients_total": self.db.query(func.count(Patient.id)).scalar() or 0,
            "completed_visits_total": self.db.query(func.count(Appointment.id)).filter(Appointment.visit_status == VisitStatus.COMPLETED).scalar() or 0,
            "cancelled_appointments_total": self.db.query(func.count(Appointment.id)).filter(Appointment.status == AppointmentStatus.CANCELLED).scalar() or 0,
            "published_services_total": self.db.query(func.count(Service.id)).filter(Service.is_published.is_(True)).scalar() or 0,
            "billing_total": self.db.query(func.coalesce(func.sum(Billing.amount), 0)).scalar() or 0,
        }

        drift: list[dict[str, object]] = []
        for key in sorted(raw_metrics):
            raw_value = raw_metrics[key]
            aggregate_value = aggregate_metrics.get(key, 0)
            delta = int(raw_value) - int(aggregate_value)
            if delta != 0:
                drift.append({
                    "metric": key,
                    "raw_value": raw_value,
                    "aggregate_value": aggregate_value,
                    "delta": delta,
                })

        return {
            "drift_detected": bool(drift),
            "aggregate_metrics": aggregate_metrics,
            "raw_metrics": raw_metrics,
            "drift": drift,
        }
