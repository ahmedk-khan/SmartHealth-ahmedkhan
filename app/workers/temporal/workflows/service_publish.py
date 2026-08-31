from datetime import timedelta
from typing import Any

from temporalio import workflow

from app.models import ServiceStatus
from app.workers.temporal.policies import BUSINESS_ACTIVITY_RETRY, TRANSIENT_ACTIVITY_RETRY
from app.workers.temporal.activities.service_publish import (
    validate_service,
    structure_service,
    chunk_service,
    embed_chunks,
    publish_service_published_event,
    mark_publish_failed,
)


@workflow.defn
class ServicePublishWorkflow:
    def __init__(self) -> None:
        self._status = ServiceStatus.PUBLISHING.value
        self._progress = {"status": self._status, "stage": "VALIDATING", "chunks_total": 0, "embeddings_generated": 0}

    @workflow.run
    async def run(self, service_id: int) -> dict[str, Any]:
        self._status = ServiceStatus.PUBLISHING.value
        try:
            published = await workflow.execute_activity(
                validate_service,
                service_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
        except Exception:
            await workflow.execute_activity(
                mark_publish_failed,
                service_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            self._status = ServiceStatus.PUBLISH_FAILED.value
            raise

        if published["status"] == ServiceStatus.PUBLISHED.value:
            self._progress = {"status": ServiceStatus.PUBLISHED.value, "stage": "COMPLETE", "chunks_total": 0, "embeddings_generated": 0}
            self._status = ServiceStatus.PUBLISHED.value
            return {"workflow_status": published["status"]}

        self._progress["stage"] = "STRUCTURING"
        try:
            service_struct = await workflow.execute_activity(
                structure_service,
                published["service"],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
            chunks = await workflow.execute_activity(
                chunk_service,
                service_struct,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
            self._progress.update({"stage": "EMBEDDING", "chunks_total": len(chunks)})
            embedded_chunks = await workflow.execute_activity(
                embed_chunks,
                chunks,
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            self._progress.update({"stage": "PERSISTING", "embeddings_generated": len(embedded_chunks)})
            await workflow.execute_activity(
                publish_service_published_event,
                {"service_id": service_id, "chunks": embedded_chunks},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
        except Exception:
            await workflow.execute_activity(
                mark_publish_failed,
                service_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            self._status = ServiceStatus.PUBLISH_FAILED.value
            raise

        self._progress.update({"stage": "COMPLETE", "status": ServiceStatus.PUBLISHED.value})
        self._status = ServiceStatus.PUBLISHED.value
        return {"workflow_status": ServiceStatus.PUBLISHED.value}

    @workflow.query(name="publish_status")
    def publish_status(self) -> str:
        return self._status

    @workflow.query(name="publish_progress")
    def publish_progress(self) -> dict[str, Any]:
        return self._progress
