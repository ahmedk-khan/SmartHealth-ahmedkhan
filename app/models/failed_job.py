import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db import Base


class FailedJob(Base):
    __tablename__ = "failed_jobs"

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255), nullable=False, index=True)
    task_id = Column(String(255), nullable=True, index=True)
    status = Column(String(50), nullable=False, default="FAILED")
    exception_type = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    traceback = Column(Text, nullable=True)
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
