import datetime
from typing import Any

from datetime import timedelta
from temporalio import activity, workflow
from sqlalchemy.orm import Session

from app import db as db_module
from app.models import ContentChunk, Service, ServiceStatus


@activity.defn
async def validate_service(service_id: int) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        service = db.query(Service).filter(Service.id == service_id).first()
        if not service:
            raise ValueError("Service not found")
        if service.status == ServiceStatus.PUBLISHED:
            return {"status": ServiceStatus.PUBLISHED.value, "service": None}
        service.status = ServiceStatus.PUBLISHING
        db.add(service)
        db.commit()
        return {
            "status": ServiceStatus.PUBLISHING.value,
            "service": {
                "id": service.id,
                "name": service.name,
                "description": service.description or "",
                "department_id": service.department_id,
            },
        }
    finally:
        db.close()


@activity.defn
async def structure_service(service_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": service_data["name"],
        "description": service_data["description"],
        "department_id": service_data["department_id"],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@activity.defn
async def chunk_service(service_struct: dict[str, Any]) -> list[dict[str, Any]]:
    description = service_struct["description"]
    chunks: list[dict[str, Any]] = []
    if not description:
        return []
    chunk_size = 120
    for idx in range(0, len(description), chunk_size):
        chunks.append({"chunk_index": idx // chunk_size, "content": description[idx : idx + chunk_size]})
    return chunks


@activity.defn
async def mark_published(service_id: int, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        service = db.query(Service).filter(Service.id == service_id).first()
        if not service:
            raise ValueError("Service not found")
        service.status = ServiceStatus.PUBLISHED
        service.is_published = True
        db.add(service)
        db.query(ContentChunk).filter(ContentChunk.service_id == service_id).delete()
        for chunk in chunks:
            db.add(
                ContentChunk(
                    service_id=service.id,
                    chunk_index=chunk["chunk_index"],
                    content=chunk["content"],
                )
            )
        db.commit()
        return {"service_id": service.id, "published": True}
    finally:
        db.close()


class ServicePublishWorkflow:
    @workflow.run
    async def run(self, service_id: int) -> dict[str, Any]:
        self._status = ServiceStatus.PUBLISHING.value
        published = await workflow.execute_activity(
            validate_service,
            service_id,
            start_to_close_timeout=workflow.Duration(seconds=30),
        )
        if published["status"] == ServiceStatus.PUBLISHED.value:
            self._status = ServiceStatus.PUBLISHED.value
            return {"workflow_status": published["status"]}

        service_struct = await workflow.execute_activity(
            structure_service,
            published["service"],
            start_to_close_timeout=workflow.Duration(seconds=30),
        )
        chunks = await workflow.execute_activity(
            chunk_service,
            service_struct,
            start_to_close_timeout=timedelta(seconds=30),
        )
        await workflow.execute_activity(
            mark_published,
            service_id,
            chunks,
            start_to_close_timeout=timedelta(seconds=30),
        )
        self._status = ServiceStatus.PUBLISHED.value
        return {"workflow_status": ServiceStatus.PUBLISHED.value}

    def __init__(self) -> None:
        self._status = ServiceStatus.PUBLISHING.value

    @workflow.query(name="publish_status")
    def publish_status(self) -> str:
        return self._status
