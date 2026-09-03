"""Business logic for the service publication Temporal workflow."""

from __future__ import annotations

import datetime
import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ExternalServiceError, NotFoundError, ValidationError
from app.core.settings import settings
from app.models import ServiceStatus
from app.repositories import ContentChunkRepository, ServiceRepository
from app.services.embedding_service import embedding_model_id, generate_embeddings
from app.services.healthcare_event_service import HealthcareEventService


class ServicePublishService:
    """Encapsulates service publish steps so Temporal activities stay thin adapters."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.services = ServiceRepository(db)
        self.chunks = ContentChunkRepository(db)

    def validate_for_publication(self, service_id: int) -> dict[str, Any]:
        service = self.services.get_for_publication(service_id)
        if not service:
            raise NotFoundError("Service not found")
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
            self.services.mark_publish_failed(service)
            raise ValidationError("Service is incomplete", detail=errors)

        self.services.mark_publishing(service)
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

    @staticmethod
    def structure_service(service_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "service_id": service_data["id"],
            "title": service_data["name"],
            "description": service_data["description"],
            "specialty": service_data["specialty"],
            "preparation_instructions": service_data["preparation_instructions"],
            "department_id": service_data["department_id"],
            "department_name": service_data["department_name"],
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    @staticmethod
    def chunk_service(service_struct: dict[str, Any]) -> list[dict[str, Any]]:
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
            content = f"{context}\n\n{description[idx : idx + chunk_size]}"
            chunks.append(
                {
                    "chunk_index": idx // chunk_size,
                    "content": content,
                    "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "service_id": service_struct.get("service_id"),
                    "department": service_struct["department_name"],
                    "specialty": service_struct.get("specialty") or None,
                    "published": True,
                }
            )
        return chunks

    async def embed_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return []

        model_id = embedding_model_id()
        service_id = chunks[0].get("service_id")
        reusable: dict[tuple[int, str], list[float]] = {}
        if service_id is not None:
            chunk_keys = [
                (
                    chunk["chunk_index"],
                    chunk.get("content_hash") or hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest(),
                )
                for chunk in chunks
            ]
            reusable = self.chunks.get_reusable_embeddings(service_id, chunk_keys, model_id)

        batch_size = settings.embedding_batch_size
        pending = []
        for chunk in chunks:
            content_hash = chunk.get("content_hash") or hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest()
            if reusable.get((chunk["chunk_index"], content_hash)) is not None:
                continue
            pending.append(chunk | {"content_hash": content_hash})

        embedded_by_key: dict[tuple[int, str], list[float]] = {}
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            embeddings = await generate_embeddings([chunk["content"] for chunk in batch])
            if len(embeddings) != len(batch):
                raise ExternalServiceError(
                    "Embedding provider returned an incomplete batch",
                    status_code=502,
                    code="EMBEDDING_BATCH_INVALID",
                )
            embedded_by_key.update(
                ((chunk["chunk_index"], chunk["content_hash"]), embedding)
                for chunk, embedding in zip(batch, embeddings)
            )

        embedded_chunks = []
        for chunk in chunks:
            content_hash = chunk.get("content_hash") or hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest()
            key = (chunk["chunk_index"], content_hash)
            embedding = reusable.get(key)
            if embedding is None:
                embedding = embedded_by_key[key]
            embedded_chunks.append(
                chunk | {"content_hash": content_hash, "embedding": embedding, "embedding_model": model_id}
            )
        return embedded_chunks

    async def persist_and_publish(self, service_id: int, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        service = self.services.get_for_publication(service_id)
        if not service:
            raise NotFoundError("Service not found")
        self.chunks.replace_for_service(service.id, chunks)
        self.services.mark_published(service, commit=False)
        await HealthcareEventService(self.db).publish_service_event_async(
            "service.published",
            service_id=service.id,
            department_id=service.department_id,
            status=service.status.value,
        )
        self.services.commit()
        return {"service_id": service.id, "published": True}

    def mark_failed(self, service_id: int) -> dict[str, Any]:
        service = self.services.get_for_publication(service_id)
        if service:
            self.services.mark_publish_failed(service)
        return {"service_id": service_id, "failed": True}
