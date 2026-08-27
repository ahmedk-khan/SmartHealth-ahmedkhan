import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base
from app.models.service import provider_services


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    bio = Column(Text, nullable=True)
    specialty = Column(String(length=140), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    user = relationship("User", back_populates="provider", uselist=False)
    department = relationship("Department", back_populates="providers")
    services = relationship(
        "Service",
        secondary=provider_services,
        back_populates="providers",
    )
    slots = relationship("Slot", back_populates="provider", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="provider")
