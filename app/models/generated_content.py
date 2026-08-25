import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String

from app.db import Base


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True, index=True)
    report_scope = Column(String(255), nullable=True)
    type = Column(String(100), nullable=False)
    content = Column(JSON, nullable=False)
    model = Column(String(255), nullable=True)
    prompt_version = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
