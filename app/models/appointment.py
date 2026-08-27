import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SLOT_RESERVED = "SLOT_RESERVED"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class VisitStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    slot_id = Column(Integer, ForeignKey("slots.id"), nullable=False)
    booking_key = Column(String(255), nullable=True, unique=True, index=True)
    booked_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(SAEnum(AppointmentStatus), nullable=False, default=AppointmentStatus.PENDING, index=True)
    visit_status = Column(SAEnum(VisitStatus), nullable=False, default=VisitStatus.NOT_STARTED)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    patient = relationship("Patient", back_populates="appointments")
    provider = relationship("Provider", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    slot = relationship("Slot", back_populates="appointment", uselist=False)
    status_history = relationship(
        "AppointmentStatusHistory",
        back_populates="appointment",
        cascade="all, delete-orphan",
        order_by="AppointmentStatusHistory.created_at",
    )
    billing = relationship("Billing", back_populates="appointment", uselist=False, cascade="all, delete-orphan")
    visit = relationship("Visit", back_populates="appointment", uselist=False)


class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False)
    status = Column(SAEnum(AppointmentStatus), nullable=False, default=AppointmentStatus.PENDING)
    from_status = Column(SAEnum(AppointmentStatus), nullable=True)
    to_status = Column(SAEnum(AppointmentStatus), nullable=True)
    actor = Column(String(255), nullable=True)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    appointment = relationship("Appointment", back_populates="status_history")
