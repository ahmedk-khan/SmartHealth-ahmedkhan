"""Client-side helpers for service publication workflows (non-deterministic I/O)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.models import ServiceStatus

logger = logging.getLogger(__name__)

_LOCAL_PUBLISH_WORKFLOWS: dict[str, dict[str, Any]] = {}


class LocalWorkflowHandle:
    """In-process workflow handle used when Temporal is unavailable."""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.run_id = _LOCAL_PUBLISH_WORKFLOWS[workflow_id].get("run_id", str(uuid.uuid4()))

    async def query(self, query_name: str) -> Any:
        if query_name == "publish_progress":
            return _LOCAL_PUBLISH_WORKFLOWS[self.workflow_id]
        if query_name != "publish_status":
            from app.core.exceptions import AppError

            raise AppError("Unsupported query", status_code=400, error_type="invalid_query")
        return _LOCAL_PUBLISH_WORKFLOWS[self.workflow_id]["status"]


def get_local_publish_progress(workflow_id: str) -> dict[str, Any] | None:
    """Return tracked progress for a locally executed publish workflow."""
    return _LOCAL_PUBLISH_WORKFLOWS.get(workflow_id)


async def run_service_publish_locally(service_id: int, workflow_id: str) -> LocalWorkflowHandle:
    """Execute the service publish pipeline inline when Temporal is unavailable."""
    from app.workers.temporal.activities.service_publish import (
        chunk_service,
        embed_chunks,
        publish_service_published_event,
        structure_service,
        validate_service,
    )

    logger.info(
        "Running service publish locally (Temporal fallback)",
        extra={"service_id": service_id, "workflow_id": workflow_id},
    )

    _LOCAL_PUBLISH_WORKFLOWS[workflow_id] = {
        "status": ServiceStatus.PUBLISHING.value,
        "stage": "VALIDATING",
        "chunks_total": 0,
        "embeddings_generated": 0,
        "run_id": str(uuid.uuid4()),
    }
    try:
        published = await validate_service(service_id)
        if published["status"] == ServiceStatus.PUBLISHED.value:
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["stage"] = "COMPLETE"
            return LocalWorkflowHandle(workflow_id)

        service_struct = await structure_service(published["service"])
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["stage"] = "CHUNKING"
        chunks = await chunk_service(service_struct)
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id].update({"stage": "EMBEDDING", "chunks_total": len(chunks)})
        embedded_chunks = await embed_chunks(chunks)
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id].update(
            {"stage": "PERSISTING", "embeddings_generated": len(embedded_chunks)}
        )
        await publish_service_published_event({"service_id": service_id, "chunks": embedded_chunks})
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["stage"] = "COMPLETE"
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
        return LocalWorkflowHandle(workflow_id)
    except Exception as exc:
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = "FAILED"
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["error"] = str(exc)
        raise
