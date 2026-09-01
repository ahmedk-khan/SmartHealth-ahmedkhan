"""Pydantic contracts for PHI-safe versioned event envelopes."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    occurred_at: datetime
    source: str
    schema_version: int = Field(default=1, ge=1)
    entity_type: str
    entity_id: str
    data: dict[str, object] = Field(default_factory=dict)
