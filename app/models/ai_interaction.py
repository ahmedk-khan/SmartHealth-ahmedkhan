import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UUID

from app.db import Base


class AIInteraction(Base):
    __tablename__ = "ai_interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    conversation_id = Column(UUID, nullable=True, index=True)
    correlation_id = Column(String(255), nullable=True, index=True)
    question = Column(Text, nullable=True)
    question_text = Column(Text, nullable=True)
    intent = Column(String(120), nullable=False)
    retrieved_ids = Column(JSON, nullable=True)
    answer = Column(Text, nullable=True)
    model = Column(String(255), nullable=True)
    prompt_version = Column(String(80), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    refused = Column(Boolean, nullable=False, default=False)
    cache_hit = Column(Boolean, nullable=False, default=False)
    answer_quality = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
