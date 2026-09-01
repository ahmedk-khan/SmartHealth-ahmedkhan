import logging
from datetime import date

from app.db import SessionLocal
from app.core.logging import get_correlation_id
from app.core.settings import settings
from app.models import GeneratedContent
from app.services.utilisation_service import UtilisationService
from app.services.llm_provider import get_llm_provider
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.celery.reports.generate_utilisation_report_task",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
)
def generate_utilisation_report_task(self, period_start: str, period_end: str, user_id: int | None = None) -> dict[str, object]:
    """Generate a utilisation report in the background and return the serializable payload."""
    import asyncio

    db = SessionLocal()
    try:
        service = UtilisationService(db, get_llm_provider())
        report = asyncio.run(service.generate(period_start, period_end))
        payload = report.model_dump(mode="json")
        generated = GeneratedContent(
            type="utilisation_report",
            report_scope=f"{period_start}_to_{period_end}",
            content=payload,
            model=settings.llm_model,
            prompt_version="PROMPT_REPORT_V1",
            initiated_by_user_id=user_id,
            correlation_id=get_correlation_id(),
        )
        db.add(generated)
        db.commit()
        return payload
    finally:
        db.close()
