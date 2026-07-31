from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from app.db import Base
from app.models.service import provider_services


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    bio = Column(Text, nullable=True)

    user = relationship("User", back_populates="provider", uselist=False)
    department = relationship("Department", back_populates="providers")
    services = relationship(
        "Service",
        secondary=provider_services,
        back_populates="providers",
    )
    slots = relationship("Slot", back_populates="provider", cascade="all, delete-orphan")
