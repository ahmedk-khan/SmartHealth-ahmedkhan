from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = Field(default=None, description="Optional conversation ID for multi-turn conversations")

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question cannot be empty")
        return normalized


class AssistantReportRequest(BaseModel):
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class AssistantCitation(BaseModel):
    service_id: int
    service_name: str
    department: str


class UtilisationReport(BaseModel):
    period_start: date
    period_end: date
    appointments_booked: int = Field(ge=0)
    completed_visits: int = Field(ge=0)
    cancellations: int = Field(ge=0)
    total_patients: int = Field(ge=0)
    failed_workflows: int = Field(ge=0)


class AssistantAnswer(BaseModel):
    answer: str
    citations: list[AssistantCitation] = Field(default_factory=list)
    refused: bool = False


class AssistantJsonAnswer(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    refused: bool = False


# Communication & Report Generation Schemas

class AppointmentSummaryRequest(BaseModel):
    """Request to generate a patient-facing appointment summary."""
    include_instructions: bool = Field(default=True, description="Include pre-visit instructions")
    include_cancellation_policy: bool = Field(default=True, description="Include cancellation policy")


class AppointmentSummary(BaseModel):
    """Patient-facing appointment summary."""
    appointment_id: int
    summary: str
    provider_name: str
    service_name: str
    appointment_date: str
    appointment_time: str
    location: str
    pre_visit_instructions: str | None = None
    cancellation_policy: str | None = None


class AppointmentFollowupRequest(BaseModel):
    """Request to generate a follow-up communication draft."""
    tone: str = Field(default="professional", description="professional, friendly, urgent")
    include_next_steps: bool = Field(default=True, description="Include recommended next steps")


class AppointmentFollowup(BaseModel):
    """Draft follow-up communication for staff review."""
    appointment_id: int
    subject: str
    body: str
    recommended_channel: str = Field(description="email, sms, or in-app")
    follow_up_actions: list[str] = Field(default_factory=list, description="Recommended actions for follow-up")
    requires_review: bool = Field(default=True, description="Whether staff should review before sending")


class GeneratedContentMetadata(BaseModel):
    """Metadata about generated content."""
    id: int
    type: str  # "summary", "followup", "utilisation_report"
    appointment_id: int | None = None
    report_scope: str | None = None
    model: str
    prompt_version: str
    created_at: str


class AppointmentSummaryResponse(BaseModel):
    success: bool = True
    data: AppointmentSummary
    metadata: GeneratedContentMetadata


class AppointmentFollowupResponse(BaseModel):
    success: bool = True
    data: AppointmentFollowup
    metadata: GeneratedContentMetadata


class AssistantAskResponse(BaseModel):
    success: bool = True
    data: AssistantJsonAnswer
    request_id: str | None = None


class ReportGenerationResponse(BaseModel):
    """Response for report generation with grounded data."""
    report: UtilisationReport
    metadata: GeneratedContentMetadata


class ReportJsonResponse(BaseModel):
    success: bool = True
    data: UtilisationReport
    metadata: GeneratedContentMetadata


class AIGenerationError(BaseModel):
    """Structured error returned in SSE `error` and failed `done` events."""
    type: str
    message: str
    code: str
    request_id: str | None = None
    detail: Any | None = None


class AIGenerationDoneResponse(BaseModel):
    """Terminal SSE `done` event payload for generation endpoints."""
    ok: bool
    content: AppointmentSummary | AppointmentFollowup | None = None
    report: UtilisationReport | None = None
    metadata: GeneratedContentMetadata | None = None
    error: AIGenerationError | None = None
