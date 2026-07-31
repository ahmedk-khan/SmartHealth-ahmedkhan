from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from app.db import Base

provider_services = Table(
    "provider_services",
    Base.metadata,
    Column("provider_id", ForeignKey("providers.id"), primary_key=True),
    Column("service_id", ForeignKey("services.id"), primary_key=True),
)


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=140), nullable=False, index=True)
    description = Column(Text, nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)

    department = relationship("Department", back_populates="services")
    providers = relationship(
        "Provider",
        secondary=provider_services,
        back_populates="services",
    )
    slots = relationship("Slot", back_populates="service", cascade="all, delete-orphan")
