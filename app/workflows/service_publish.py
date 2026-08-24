import datetime
from typing import Any

from datetime import timedelta
from temporalio import activity, workflow
from sqlalchemy.orm import Session

from app import db as db_module
from app.core.exceptions import AppError
from app.models import ServiceStatus
from app.repositories import ContentChunkRepository, ServiceRepository
from app.services.embedding_service import generate_embeddings


@activity.defn
async def validate_service(service_id: int) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        repository = ServiceRepository(db)
        service = repository.get_for_publication(service_id)
        if not service:
            raise AppError("Service not found", status_code=404, error_type="not_found")
        if service.status == ServiceStatus.PUBLISHED:
            return {"status": ServiceStatus.PUBLISHED.value, "service": None}
        errors = []
        if not service.description:
            errors.append("description is required")
        if not service.preparation_instructions:
            errors.append("preparation_instructions is required")
        if not service.department:
            errors.append("owning department is required")
        if errors:
            ServiceRepository(db).mark_publish_failed(service)
            raise AppError("Service is incomplete", status_code=422, error_type="publish_validation_failed", detail=errors)
        repository.mark_publishing(service)
        return {
            "status": ServiceStatus.PUBLISHING.value,
            "service": {
                "id": service.id,
                "name": service.name,
                "description": service.description or "",
                "specialty": service.specialty or "",
                "preparation_instructions": service.preparation_instructions or "",
                "department_id": service.department_id,
                "department_name": service.department.name,
            },
        }
    finally:
        db.close()


@activity.defn
async def structure_service(service_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": service_data["name"],
        "description": service_data["description"],
        "specialty": service_data["specialty"],
        "preparation_instructions": service_data["preparation_instructions"],
        "department_id": service_data["department_id"],
        "department_name": service_data["department_name"],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@activity.defn
async def chunk_service(service_struct: dict[str, Any]) -> list[dict[str, Any]]:
    description = service_struct.get("description", "")
    chunks: list[dict[str, Any]] = []
    context = "\n".join(
        (
            f"Service: {service_struct['title']}",
            f"Department: {service_struct.get('department_name', 'Not specified')}",
            f"Specialty: {service_struct.get('specialty') or 'Not specified'}",
            f"Preparation instructions: {service_struct.get('preparation_instructions') or 'Not specified'}",
        )
    )
    chunk_size = 120
    for idx in range(0, max(len(description), 1), chunk_size):
        chunks.append(
            {
                "chunk_index": idx // chunk_size,
                "content": f"{context}\n\n{description[idx : idx + chunk_size]}",
            }
        )
    return chunks


@activity.defn
async def embed_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    embeddings = await generate_embeddings([chunk["content"] for chunk in chunks])
    return [chunk | {"embedding": embedding} for chunk, embedding in zip(chunks, embeddings)]


@activity.defn
async def mark_published(payload: dict[str, Any]) -> dict[str, Any]:
    service_id = payload["service_id"]
    chunks = payload["chunks"]
    db: Session = db_module.SessionLocal()
    try:
        service_repository = ServiceRepository(db)
        chunk_repository = ContentChunkRepository(db)
        service = service_repository.get_for_publication(service_id)
        if not service:
            raise AppError("Service not found", status_code=404, error_type="not_found")
        chunk_repository.replace_for_service(service.id, chunks)
        service_repository.mark_published(service)
        from app.services.healthcare_event_service import HealthcareEventService
        HealthcareEventService().publish_service_event("service.published", service_id=service.id, department_id=service.department_id, status=service.status.value)
        return {"service_id": service.id, "published": True}
    finally:
        db.close()


@activity.defn
async def mark_publish_failed(service_id: int) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        service = ServiceRepository(db).get_for_publication(service_id)
        if service:
            ServiceRepository(db).mark_publish_failed(service)
        return {"service_id": service_id, "failed": True}
    finally:
        db.close()


@workflow.defn
class ServicePublishWorkflow:
    @workflow.run
    async def run(self, service_id: int) -> dict[str, Any]:
        self._status = ServiceStatus.PUBLISHING.value
        try:
            published = await workflow.execute_activity(
                validate_service,
                service_id,
                start_to_close_timeout=timedelta(seconds=30),
            )
        except Exception:
            await workflow.execute_activity(mark_publish_failed, service_id, start_to_close_timeout=timedelta(seconds=30))
            self._status = ServiceStatus.PUBLISH_FAILED.value
            raise
        if published["status"] == ServiceStatus.PUBLISHED.value:
            self._progress = {"status": ServiceStatus.PUBLISHED.value, "stage": "COMPLETE", "chunks_total": 0, "embeddings_generated": 0}
            self._status = ServiceStatus.PUBLISHED.value
            return {"workflow_status": published["status"]}

        self._progress["stage"] = "STRUCTURING"
        try:
            service_struct = await workflow.execute_activity(structure_service, published["service"], start_to_close_timeout=timedelta(seconds=30))
            chunks = await workflow.execute_activity(chunk_service, service_struct, start_to_close_timeout=timedelta(seconds=30))
            self._progress.update({"stage": "EMBEDDING", "chunks_total": len(chunks)})
            embedded_chunks = await workflow.execute_activity(embed_chunks, chunks, start_to_close_timeout=timedelta(seconds=120))
            self._progress.update({"stage": "PERSISTING", "embeddings_generated": len(embedded_chunks)})
            await workflow.execute_activity(
                mark_published,
                {"service_id": service_id, "chunks": embedded_chunks},
                start_to_close_timeout=timedelta(seconds=30),
            )
        except Exception:
            await workflow.execute_activity(mark_publish_failed, service_id, start_to_close_timeout=timedelta(seconds=30))
            self._status = ServiceStatus.PUBLISH_FAILED.value
            raise
        self._progress.update({"stage": "COMPLETE", "status": ServiceStatus.PUBLISHED.value})
        self._status = ServiceStatus.PUBLISHED.value
        return {"workflow_status": ServiceStatus.PUBLISHED.value}

    def __init__(self) -> None:
        self._status = ServiceStatus.PUBLISHING.value
        self._progress = {"status": self._status, "stage": "VALIDATING", "chunks_total": 0, "embeddings_generated": 0}

    @workflow.query(name="publish_status")
    def publish_status(self) -> str:
        return self._status

    @workflow.query(name="publish_progress")
    def publish_progress(self) -> dict[str, Any]:
        return self._progress
