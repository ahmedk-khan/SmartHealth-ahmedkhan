import datetime

from sqlalchemy import func

from app.core.exceptions import AppError
from app.models import AnalyticsAppointmentDaily, AnalyticsDaily, AnalyticsServiceDaily, Appointment, AppointmentStatus, FailedJob, Patient, Slot, Visit, VisitStatus
from app.services.base import BaseService


class AnalyticsService(BaseService):
    def _raw_dashboard_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, int | float]:
        appointments = self.db.query(Appointment)
        if start_date:
            appointments = appointments.filter(func.date(Appointment.created_at) >= datetime.date.fromisoformat(start_date))
        if end_date:
            appointments = appointments.filter(func.date(Appointment.created_at) <= datetime.date.fromisoformat(end_date))

        appointments_total = appointments.count()
        cancelled_appointments_total = appointments.filter(Appointment.status == AppointmentStatus.CANCELLED).count()
        completed_visits_total = appointments.filter(Appointment.visit_status == VisitStatus.COMPLETED).count()
        patients_total = self.db.query(func.count(Patient.id)).scalar() or 0
        wait_query = self.db.query(Visit.checked_in_at, Slot.start_datetime).join(
            Appointment, Appointment.id == Visit.appointment_id,
        ).join(Slot, Slot.id == Appointment.slot_id).filter(
            Visit.checked_in_at.isnot(None),
        )
        if start_date:
            wait_query = wait_query.filter(func.date(Appointment.created_at) >= datetime.date.fromisoformat(start_date))
        if end_date:
            wait_query = wait_query.filter(func.date(Appointment.created_at) <= datetime.date.fromisoformat(end_date))
        wait_rows = wait_query.all()
        average_wait_seconds = (
            sum((checked_in_at - scheduled_at).total_seconds() for checked_in_at, scheduled_at in wait_rows) / len(wait_rows)
            if wait_rows else 0.0
        )
        return {
            "appointments_total": int(appointments_total),
            "patients_total": int(patients_total),
            "completed_visits_total": int(completed_visits_total),
            "cancelled_appointments_total": int(cancelled_appointments_total),
            "cancellation_rate": cancelled_appointments_total / appointments_total if appointments_total else 0.0,
            "average_wait_seconds": float(average_wait_seconds),
            "failed_workflows_total": int(self.db.query(func.count(FailedJob.id)).scalar() or 0),
        }

    def rollup_daily_metrics(self, day: str | None = None) -> dict[str, object]:
        try:
            target_day = datetime.date.fromisoformat(day) if day else datetime.date.today()
        except ValueError as exc:
            raise AppError("Invalid date format", status_code=400, error_type="validation_error", detail=str(exc)) from exc

        aggregate = self.db.query(AnalyticsDaily).filter(AnalyticsDaily.date == target_day).first()

        return {
            "date": target_day.isoformat(),
            "appointments_booked": int(aggregate.appointments_booked if aggregate else 0),
            "completed_visits": int(aggregate.completed_visits if aggregate else 0),
            "cancellations": int(aggregate.cancellations if aggregate else 0),
            "average_wait_seconds": float(aggregate.avg_wait_seconds if aggregate and aggregate.avg_wait_seconds is not None else 0),
            "failed_workflows": int(aggregate.failed_workflows if aggregate else 0),
            "patients_total": int(aggregate.total_patients if aggregate else 0),
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

    def get_dashboard_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, int | float]:
        daily = self.db.query(AnalyticsDaily)
        if start_date:
            daily = daily.filter(AnalyticsDaily.date >= datetime.date.fromisoformat(start_date))
        if end_date:
            daily = daily.filter(AnalyticsDaily.date <= datetime.date.fromisoformat(end_date))
        daily_rows = daily.subquery()
        if not self.db.query(daily_rows.c.date).first():
            return self._raw_dashboard_metrics(start_date, end_date)
        appointments_total = self.db.query(func.coalesce(func.sum(daily_rows.c.appointments_booked), 0)).scalar() or 0
        cancelled_appointments_total = self.db.query(func.coalesce(func.sum(daily_rows.c.cancellations), 0)).scalar() or 0
        completed_visits_total = self.db.query(func.coalesce(func.sum(daily_rows.c.completed_visits), 0)).scalar() or 0
        patient_rollups = self.db.query(func.count(func.distinct(AnalyticsAppointmentDaily.patient_id))).filter(
            AnalyticsAppointmentDaily.patient_id.isnot(None),
        )
        if start_date:
            patient_rollups = patient_rollups.filter(AnalyticsAppointmentDaily.event_date >= start_date)
        if end_date:
            patient_rollups = patient_rollups.filter(AnalyticsAppointmentDaily.event_date <= end_date)
        patients_total = patient_rollups.scalar() or 0
        wait_total = self.db.query(func.coalesce(func.sum(daily_rows.c.avg_wait_seconds * daily_rows.c.wait_samples), 0)).scalar() or 0
        wait_samples = self.db.query(func.coalesce(func.sum(daily_rows.c.wait_samples), 0)).scalar() or 0
        cancellation_rate = (cancelled_appointments_total / appointments_total) if appointments_total else 0.0

        return {
            "appointments_total": int(appointments_total),
            "patients_total": int(patients_total),
            "completed_visits_total": int(completed_visits_total),
            "cancelled_appointments_total": int(cancelled_appointments_total),
            "cancellation_rate": float(cancellation_rate),
            "average_wait_seconds": float(wait_total / wait_samples) if wait_samples else 0.0,
            "failed_workflows_total": int(self.db.query(func.coalesce(func.sum(daily_rows.c.failed_workflows), 0)).scalar() or 0),
        }

    def reconcile_metrics(self) -> dict[str, object]:
        aggregate_metrics = self.get_dashboard_metrics()

        wait_rows = self.db.query(Visit.checked_in_at, Slot.start_datetime).join(
            Appointment, Appointment.id == Visit.appointment_id,
        ).join(Slot, Slot.id == Appointment.slot_id).filter(Visit.checked_in_at.isnot(None)).all()
        raw_wait = (
            sum((checked_in_at - scheduled_at).total_seconds() for checked_in_at, scheduled_at in wait_rows) / len(wait_rows)
            if wait_rows else 0.0
        )
        raw_metrics = {
            "appointments_total": self.db.query(func.count(Appointment.id)).scalar() or 0,
            "patients_total": self.db.query(func.count(Patient.id)).scalar() or 0,
            "completed_visits_total": self.db.query(func.count(Appointment.id)).filter(Appointment.visit_status == VisitStatus.COMPLETED).scalar() or 0,
            "cancelled_appointments_total": self.db.query(func.count(Appointment.id)).filter(Appointment.status == AppointmentStatus.CANCELLED).scalar() or 0,
            "cancellation_rate": 0.0,
            "average_wait_seconds": raw_wait,
            "failed_workflows_total": self.db.query(func.count(FailedJob.id)).scalar() or 0,
        }
        raw_appointments = raw_metrics["appointments_total"]
        raw_cancellations = raw_metrics["cancelled_appointments_total"]
        raw_metrics["cancellation_rate"] = raw_cancellations / raw_appointments if raw_appointments else 0.0

        drift: list[dict[str, object]] = []
        for key in sorted(raw_metrics):
            raw_value = raw_metrics[key]
            aggregate_value = aggregate_metrics.get(key, 0)
            delta = float(raw_value) - float(aggregate_value)
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
