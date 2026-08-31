from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

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
