import json

from app.models import FailedJob
from app.repositories.failed_jobs import FailedJobRepository
from app.services.base import BaseService


class FailedJobService(BaseService):
    def __init__(self, db):
        super().__init__(db)
        self.repository = FailedJobRepository(db)

    def record_failure(self, task_name: str, task_id: str | None, exc: BaseException, payload: dict | None = None, traceback_text: str | None = None) -> FailedJob:
        self.repository.rollback()
        failed_job = FailedJob(
            task_name=task_name,
            task_id=task_id,
            status="FAILED",
            exception_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback_text,
            payload=json.dumps(payload, default=str) if payload is not None else None,
        )
        return self.repository.record_failure(failed_job)
