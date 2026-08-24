import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    first_name = Column(String(length=120), nullable=True)
    last_name = Column(String(length=120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    user = relationship("User", back_populates="patient", uselist=False)
    slots = relationship("Slot", back_populates="patient")
    appointments = relationship("Appointment", back_populates="patient")

    @property
    def email(self):
        return self.user.email if self.user else None
