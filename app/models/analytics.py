import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint

from app.db import Base


class AnalyticsProcessedEvent(Base):
    __tablename__ = "analytics_processed_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(128), unique=True, nullable=False, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    topic = Column(String(120), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    processed_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)


class AnalyticsAppointmentDaily(Base):
    __tablename__ = "analytics_appointments_daily"

    id = Column(Integer, primary_key=True, index=True)
    event_date = Column(String(10), nullable=False, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    appointment_id = Column(Integer, nullable=False, index=True)
    patient_id = Column(Integer, nullable=True, index=True)
    provider_id = Column(Integer, nullable=True, index=True)
    service_id = Column(Integer, nullable=True, index=True)
    slot_id = Column(Integer, nullable=True, index=True)
    status = Column(String(40), nullable=True)
    visit_status = Column(String(40), nullable=True)
    total_events = Column(Integer, nullable=False, default=0)
    last_event_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_date", "event_type", "appointment_id", name="uq_analytics_appointment_daily"),
    )


class AnalyticsServiceDaily(Base):
    __tablename__ = "analytics_services_daily"

    id = Column(Integer, primary_key=True, index=True)
    event_date = Column(String(10), nullable=False, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    service_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=True, index=True)
    status = Column(String(40), nullable=True)
    total_events = Column(Integer, nullable=False, default=0)
    last_event_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_date", "event_type", "service_id", name="uq_analytics_service_daily"),
    )
