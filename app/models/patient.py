from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.db import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    user = relationship("User", back_populates="patient", uselist=False)
    slots = relationship("Slot", back_populates="patient")
