import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db import Base


class ContentChunk(Base):
    __tablename__ = "content_chunks"
    __table_args__ = (UniqueConstraint("service_id", "chunk_index", name="uq_content_chunk_service_index"),)

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    department = Column(String(120), nullable=False)
    specialty = Column(String(140), nullable=True)
    published = Column(Boolean, nullable=False, default=False)
    source_type = Column(String(80), nullable=False, default="service")
    source_id = Column(Integer, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    embedding = Column(Vector(384), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    service = relationship("Service", back_populates="content_chunks")
