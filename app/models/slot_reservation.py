import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer

from app.db import Base


class SlotReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    COMMITTED = "COMMITTED"


class SlotReservation(Base):
    __tablename__ = "slot_reservations"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False, index=True)
    slot_id = Column(Integer, ForeignKey("slots.id"), nullable=False, index=True)
    status = Column(SAEnum(SlotReservationStatus), nullable=False, default=SlotReservationStatus.RESERVED)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
