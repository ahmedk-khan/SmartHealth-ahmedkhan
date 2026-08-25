import datetime

from sqlalchemy import Column, Date, DateTime, Integer

from app.db import Base


class AnalyticsDaily(Base):
    __tablename__ = "analytics_daily"

    date = Column(Date, primary_key=True, index=True)
    appointments_booked = Column(Integer, nullable=False, default=0)
    completed_visits = Column(Integer, nullable=False, default=0)
    cancellations = Column(Integer, nullable=False, default=0)
    avg_wait_seconds = Column(Integer, nullable=True)
    total_patients = Column(Integer, nullable=False, default=0)
    failed_workflows = Column(Integer, nullable=False, default=0)
    wait_samples = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
