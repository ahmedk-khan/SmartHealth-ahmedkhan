"""Thin Temporal adapters for the service publication workflow."""

from __future__ import annotations

from typing import Any

from temporalio import activity

from app.core.exceptions import AppError
from app.services.service_publish_service import ServicePublishService
from app.workers.temporal.activity_errors import to_non_retryable_application_error
from app.workers.temporal.activity_session import activity_session


def _run_db_activity(action):
    try:
        with activity_session() as db:
            return action(ServicePublishService(db))
    except AppError as exc:
        raise to_non_retryable_application_error(exc) from exc


@activity.defn
async def validate_service(service_id: int) -> dict[str, Any]:
    return _run_db_activity(lambda service: service.validate_for_publication(service_id))


@activity.defn
async def structure_service(service_data: dict[str, Any]) -> dict[str, Any]:
    return ServicePublishService.structure_service(service_data)


@activity.defn
async def chunk_service(service_struct: dict[str, Any]) -> list[dict[str, Any]]:
    return ServicePublishService.chunk_service(service_struct)


@activity.defn
async def embed_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        with activity_session() as db:
            return await ServicePublishService(db).embed_chunks(chunks)
    except AppError as exc:
        raise to_non_retryable_application_error(exc) from exc


@activity.defn
async def publish_service_published_event(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with activity_session() as db:
            return await ServicePublishService(db).persist_and_publish(
                payload["service_id"],
                payload["chunks"],
            )
    except AppError as exc:
        raise to_non_retryable_application_error(exc) from exc


@activity.defn
async def mark_publish_failed(service_id: int) -> dict[str, Any]:
    return _run_db_activity(lambda service: service.mark_failed(service_id))
