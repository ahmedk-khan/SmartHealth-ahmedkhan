from pydantic import BaseModel, Field


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AssistantCitation(BaseModel):
    service_id: int
    service_name: str
    department: str


class UtilisationReport(BaseModel):
    period_start: str
    period_end: str
    appointments_booked: int = Field(ge=0)
    completed_visits: int = Field(ge=0)
    cancellations: int = Field(ge=0)
    total_patients: int = Field(ge=0)
    failed_workflows: int = Field(ge=0)


class AssistantAnswer(BaseModel):
    answer: str
    citations: list[AssistantCitation] = Field(default_factory=list)
    refused: bool = False
