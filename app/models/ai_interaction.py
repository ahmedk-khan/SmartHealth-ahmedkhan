import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text

from app.db import Base


class AIInteraction(Base):
    __tablename__ = "ai_interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    intent = Column(String(120), nullable=False)
    retrieved_ids = Column(JSON, nullable=True)
    answer = Column(Text, nullable=True)
    model = Column(String(255), nullable=True)
    prompt_version = Column(String(80), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    refused = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
