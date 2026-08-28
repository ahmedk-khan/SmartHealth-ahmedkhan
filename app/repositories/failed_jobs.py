from app.models import FailedJob
from app.repositories.base import BaseRepository


class FailedJobRepository(BaseRepository):
    def record_failure(self, failed_job: FailedJob) -> FailedJob:
        self.add(failed_job)
        self.commit()
        self.refresh(failed_job)
        return failed_job
