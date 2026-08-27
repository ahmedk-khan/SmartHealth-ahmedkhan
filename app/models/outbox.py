import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String

from app.db import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(128), nullable=True, unique=True, index=True)
    event_type = Column(String(120), nullable=False, index=True)
    entity_type = Column(String(80), nullable=False)
    entity_id = Column(String(80), nullable=False)
    payload = Column(JSON, nullable=False)
    correlation_id = Column(String(128), nullable=True, index=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(30), nullable=False, default="PENDING", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
