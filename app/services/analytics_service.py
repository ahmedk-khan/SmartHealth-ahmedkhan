import datetime

from app.core.exceptions import app_error
from app.repositories.analytics import AnalyticsRepository
from app.services.base import BaseService


class AnalyticsService(BaseService):
    def __init__(self, db):
        super().__init__(db)
        self.repository = AnalyticsRepository(db)

    def _raw_dashboard_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, int | float]:
        return self.repository.raw_dashboard_metrics(start_date, end_date)

    def rollup_daily_metrics(self, day: str | None = None) -> dict[str, object]:
        try:
            target_day = datetime.date.fromisoformat(day) if day else datetime.date.today()
        except ValueError as exc:
            raise app_error("Invalid date format", status_code=400, error_type="validation_error", detail=str(exc)) from exc

        aggregate = self.repository.get_daily(target_day)

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
        return self.repository.aggregate_metric(event_type, visit_status=visit_status)

    def _aggregate_service_metric(self, event_type: str) -> int:
        return self.repository.aggregate_service_metric(event_type)

    def get_dashboard_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, int | float]:
        try:
            rollup_metrics = self.repository.dashboard_rollup_metrics(start_date, end_date)
        except ValueError as exc:
            raise app_error("Invalid analytics date range", status_code=400, error_type="validation_error") from exc
        return rollup_metrics if rollup_metrics is not None else self._raw_dashboard_metrics(start_date, end_date)

    def reconcile_metrics(self) -> dict[str, object]:
        aggregate_metrics = self.get_dashboard_metrics()

        raw_metrics = self.repository.raw_reconciliation_metrics()
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
