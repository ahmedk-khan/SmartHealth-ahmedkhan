import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.db import Base


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = (UniqueConstraint("event_id", "consumer", name="uq_processed_event_consumer"),)

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(128), nullable=False, index=True)
    consumer = Column(String(128), nullable=False)
    processed_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
