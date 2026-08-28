import datetime
from typing import Any

from sqlalchemy import func
from app.models import (
    AnalyticsAppointmentDaily,
    AnalyticsDaily,
    AnalyticsProcessedEvent,
    AnalyticsServiceDaily,
    Appointment,
    AppointmentStatus,
    FailedJob,
    Patient,
    Slot,
    Visit,
    VisitStatus,
)
from app.repositories.base import BaseRepository


class AnalyticsRepository(BaseRepository):
    def stage_processed_event(self, event_id: str, event_type: str, topic: str, payload: dict[str, Any]) -> None:
        """Stage a processed event and flush it without committing the transaction."""
        self.add(AnalyticsProcessedEvent(
            event_id=str(event_id),
            event_type=event_type,
            topic=topic,
            payload=payload,
        ))
        self.flush()

    def get_processed_event(self, event_id: str) -> AnalyticsProcessedEvent | None:
        """Return a processed analytics event by event ID or None."""
        return self.db.query(AnalyticsProcessedEvent).filter(AnalyticsProcessedEvent.event_id == event_id).first()

    def add_processed_event(self, event: AnalyticsProcessedEvent) -> None:
        """Add a processed analytics event without committing the transaction."""
        self.add(event)

    def get_appointment_daily(self, event_date: str, event_type: str, appointment_id: int) -> AnalyticsAppointmentDaily | None:
        """Return an appointment daily record matching date, type, and appointment ID."""
        return self.db.query(AnalyticsAppointmentDaily).filter(
            AnalyticsAppointmentDaily.event_date == event_date,
            AnalyticsAppointmentDaily.event_type == event_type,
            AnalyticsAppointmentDaily.appointment_id == appointment_id,
        ).first()

    def add_appointment_daily(self, record: AnalyticsAppointmentDaily) -> None:
        """Add an appointment daily record without committing the transaction."""
        self.add(record)

    def update_appointment_metrics(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("event_type", "unknown"))
        appointment_id = payload.get("appointment_id")
        patient_id = payload.get("patient_id")
        provider_id = payload.get("provider_id")
        service_id = payload.get("service_id")
        slot_id = payload.get("slot_id")
        status = payload.get("status")
        visit_status = payload.get("visit_status")
        occurred_at = payload.get("occurred_at")
        try:
            event_date = datetime.datetime.fromisoformat(str(occurred_at)).date().isoformat() if occurred_at else datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        except ValueError:
            event_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()

        if appointment_id is None:
            return

        record = self.get_appointment_daily(event_date, event_type, int(appointment_id))
        if record is None:
            record = AnalyticsAppointmentDaily(
                event_date=event_date,
                event_type=event_type,
                appointment_id=int(appointment_id),
                patient_id=int(patient_id) if patient_id is not None else None,
                provider_id=int(provider_id) if provider_id is not None else None,
                service_id=int(service_id) if service_id is not None else None,
                slot_id=int(slot_id) if slot_id is not None else None,
                status=str(status) if status is not None else None,
                visit_status=str(visit_status) if visit_status is not None else None,
                total_events=0,
            )
            self.add_appointment_daily(record)

        record.total_events += 1
        record.patient_id = int(patient_id) if patient_id is not None else record.patient_id
        record.provider_id = int(provider_id) if provider_id is not None else record.provider_id
        record.service_id = int(service_id) if service_id is not None else record.service_id
        record.slot_id = int(slot_id) if slot_id is not None else record.slot_id
        record.status = str(status) if status is not None else record.status
        record.visit_status = str(visit_status) if visit_status is not None else record.visit_status
        record.last_event_at = datetime.datetime.now(datetime.timezone.utc)
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        daily = self.get_or_create_daily_for_consumer(event_date)
        if event_type == "appointment.created":
            daily.appointments_booked += 1
        elif event_type == "appointment.cancelled":
            daily.cancellations += 1
        elif event_type in {"visit.completed", "appointment.visit_status_changed"} and visit_status == "COMPLETED":
            daily.completed_visits += 1
            if payload.get("wait_seconds") is not None:
                wait_seconds = int(payload["wait_seconds"])
                daily.avg_wait_seconds = int(((daily.avg_wait_seconds or 0) * daily.wait_samples + wait_seconds) / (daily.wait_samples + 1))
                daily.wait_samples += 1
        if event_type == "appointment.created" and payload.get("patient_id") is not None:
            patient_id = int(payload["patient_id"])
            if not self.has_patient_appointment_metric(patient_id, record.id):
                daily.total_patients += 1

    def has_patient_appointment_metric(self, patient_id: int, record_id: int) -> bool:
        """Return whether another appointment metric exists for the patient."""
        return self.db.query(AnalyticsAppointmentDaily).filter(
            AnalyticsAppointmentDaily.patient_id == patient_id,
            AnalyticsAppointmentDaily.id != record_id,
        ).first() is not None

    def get_or_create_daily_for_consumer(self, event_date: str) -> AnalyticsDaily:
        """Return or flush-create the daily analytics aggregate for an event date."""
        daily = self.db.query(AnalyticsDaily).filter(AnalyticsDaily.date == event_date).first()
        if daily is None:
            daily = AnalyticsDaily(date=datetime.date.fromisoformat(event_date))
            self.add(daily)
            self.flush()
        return daily

    def get_service_daily(self, event_date: str, event_type: str, service_id: int) -> AnalyticsServiceDaily | None:
        """Return a service daily record matching date, type, and service ID."""
        return self.db.query(AnalyticsServiceDaily).filter(
            AnalyticsServiceDaily.event_date == event_date,
            AnalyticsServiceDaily.event_type == event_type,
            AnalyticsServiceDaily.service_id == service_id,
        ).first()

    def add_service_daily(self, record: AnalyticsServiceDaily) -> None:
        """Add a service daily record without committing the transaction."""
        self.add(record)

    def update_service_metrics(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("event_type", "unknown"))
        service_id = payload.get("service_id")
        department_id = payload.get("department_id")
        status = payload.get("status")
        occurred_at = payload.get("occurred_at")
        try:
            event_date = datetime.datetime.fromisoformat(str(occurred_at)).date().isoformat() if occurred_at else datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        except ValueError:
            event_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()

        if service_id is None:
            return

        record = self.get_service_daily(event_date, event_type, int(service_id))
        if record is None:
            record = AnalyticsServiceDaily(
                event_date=event_date,
                event_type=event_type,
                service_id=int(service_id),
                department_id=int(department_id) if department_id is not None else None,
                status=str(status) if status is not None else None,
                total_events=0,
            )
            self.add_service_daily(record)

        record.total_events += 1
        record.department_id = int(department_id) if department_id is not None else record.department_id
        record.status = str(status) if status is not None else record.status
        record.last_event_at = datetime.datetime.now(datetime.timezone.utc)
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def raw_dashboard_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, int | float]:
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

    def get_daily(self, target_day: datetime.date) -> AnalyticsDaily | None:
        return self.db.query(AnalyticsDaily).filter(AnalyticsDaily.date == target_day).first()

    def aggregate_metric(self, event_type: str, *, visit_status: str | None = None) -> int:
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

    def aggregate_service_metric(self, event_type: str) -> int:
        value = (
            self.db.query(func.coalesce(func.sum(AnalyticsServiceDaily.total_events), 0))
            .filter(AnalyticsServiceDaily.event_type == event_type)
            .scalar()
            or 0
        )
        return int(value)

    def dashboard_rollup_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, int | float] | None:
        daily = self.db.query(AnalyticsDaily)
        if start_date:
            daily = daily.filter(AnalyticsDaily.date >= datetime.date.fromisoformat(start_date))
        if end_date:
            daily = daily.filter(AnalyticsDaily.date <= datetime.date.fromisoformat(end_date))
        daily_rows = daily.subquery()
        if not self.db.query(daily_rows.c.date).first():
            return None
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

    def raw_reconciliation_metrics(self) -> dict[str, int | float]:
        wait_rows = self.db.query(Visit.checked_in_at, Slot.start_datetime).join(
            Appointment, Appointment.id == Visit.appointment_id,
        ).join(Slot, Slot.id == Appointment.slot_id).filter(Visit.checked_in_at.isnot(None)).all()
        raw_wait = (
            sum((checked_in_at - scheduled_at).total_seconds() for checked_in_at, scheduled_at in wait_rows) / len(wait_rows)
            if wait_rows else 0.0
        )
        return {
            "appointments_total": self.db.query(func.count(Appointment.id)).scalar() or 0,
            "patients_total": self.db.query(func.count(Patient.id)).scalar() or 0,
            "completed_visits_total": self.db.query(func.count(Appointment.id)).filter(Appointment.visit_status == VisitStatus.COMPLETED).scalar() or 0,
            "cancelled_appointments_total": self.db.query(func.count(Appointment.id)).filter(Appointment.status == AppointmentStatus.CANCELLED).scalar() or 0,
            "cancellation_rate": 0.0,
            "average_wait_seconds": raw_wait,
            "failed_workflows_total": self.db.query(func.count(FailedJob.id)).scalar() or 0,
        }
