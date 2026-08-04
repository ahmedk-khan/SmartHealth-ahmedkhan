import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SAEnum, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class UserRole(str, Enum):
    patient = "patient"
    provider = "provider"
    front_desk = "front_desk"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(length=255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(length=255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.patient)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    patient = relationship("Patient", back_populates="user", uselist=False, cascade="all, delete-orphan")
    provider = relationship("Provider", back_populates="user", uselist=False, cascade="all, delete-orphan")
