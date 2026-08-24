import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Table, Text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from app.db import Base

provider_services = Table(
    "provider_services",
    Base.metadata,
    Column("provider_id", ForeignKey("providers.id"), primary_key=True),
    Column("service_id", ForeignKey("services.id"), primary_key=True),
)


class ServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHING = "UNPUBLISHING"
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISH_FAILED = "PUBLISH_FAILED"


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=140), nullable=False, index=True)
    description = Column(Text, nullable=True)
    specialty = Column(String(length=140), nullable=True)
    preparation_instructions = Column(Text, nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    is_published = Column(Boolean, nullable=False, default=False)
    status = Column(SAEnum(ServiceStatus), nullable=False, default=ServiceStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    department = relationship("Department", back_populates="services")
    providers = relationship(
        "Provider",
        secondary=provider_services,
        back_populates="services",
    )
    slots = relationship("Slot", back_populates="service", cascade="all, delete-orphan")
    content_chunks = relationship("ContentChunk", back_populates="service", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="service")

    @hybrid_property
    def published(self):
        return self.status == ServiceStatus.PUBLISHED
