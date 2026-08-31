import json

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
        source = {
            "period_start": period_start,
            "period_end": period_end,
            "appointments_booked": values["appointments_total"],
            "completed_visits": values["completed_visits_total"],
            "cancellations": values["cancelled_appointments_total"],
            "total_patients": values["patients_total"],
            "failed_workflows": values["failed_workflows_total"],
        }
        prompt = PROMPT_REPORT_V1.format(analytics=json.dumps(source, sort_keys=True))
        last_error = ""
        for attempt in range(2):
            raw = await self.provider.complete_json(prompt if not last_error else f"{prompt}\nPrevious validation error: {last_error}")
            try:
                report = UtilisationReport.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                continue
            # Analytics, rather than model output, is authoritative for every number.
            return report.model_copy(update=source)
        raise app_error("The utilisation report could not be validated", status_code=502, error_type="report_invalid")