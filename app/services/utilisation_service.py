import json
from datetime import date

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import app_error
from app.repositories.analytics import AnalyticsRepository
from app.schemas.assistant import UtilisationReport
from app.services.assistant_prompts import PROMPT_REPORT_V1
from app.services.llm_provider import LLMProvider


class UtilisationService:
    def __init__(self, db: Session, provider: LLMProvider) -> None:
        self.analytics = AnalyticsRepository(db)
        self.provider = provider

    async def generate(self, period_start: str, period_end: str) -> UtilisationReport:
        values = self.analytics.dashboard_rollup_metrics(period_start, period_end)
        if values is None:
            values = {"appointments_total": 0, "completed_visits_total": 0, "cancelled_appointments_total": 0, "patients_total": 0, "failed_workflows_total": 0}
        try:
            source = {
                "period_start": date.fromisoformat(period_start),
                "period_end": date.fromisoformat(period_end),
                "appointments_booked": values["appointments_total"],
                "completed_visits": values["completed_visits_total"],
                "cancellations": values["cancelled_appointments_total"],
                "total_patients": values["patients_total"],
                "failed_workflows": values["failed_workflows_total"],
            }
        except ValueError as exc:
            raise app_error("Invalid utilisation report period", status_code=422, error_type="validation_error") from exc
        prompt_source = {
            **source,
            "period_start": source["period_start"].isoformat(),
            "period_end": source["period_end"].isoformat(),
        }
        prompt = PROMPT_REPORT_V1.format(analytics=json.dumps(prompt_source, sort_keys=True))
        last_error = ""
        for attempt in range(2):
            raw = await self.provider.complete_json(prompt if not last_error else f"{prompt}\nPrevious validation error: {last_error}")
            try:
                report = UtilisationReport.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                continue
            # Analytics, rather than model output, is authoritative for every number.
            return UtilisationReport.model_validate({**report.model_dump(), **source})
        raise app_error("The utilisation report could not be validated", status_code=502, error_type="report_invalid")
