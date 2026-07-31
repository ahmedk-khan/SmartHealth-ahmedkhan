import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SAEnum, Integer, String

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
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
