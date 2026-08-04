import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.db import Base


class SlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class Slot(Base):
    __tablename__ = "slots"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    status = Column(SAEnum(SlotStatus), nullable=False, default=SlotStatus.AVAILABLE)
    start_datetime = Column(DateTime(timezone=True), nullable=False)
    end_datetime = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    provider = relationship("Provider", back_populates="slots")
    service = relationship("Service", back_populates="slots")
    patient = relationship("Patient", back_populates="slots")
