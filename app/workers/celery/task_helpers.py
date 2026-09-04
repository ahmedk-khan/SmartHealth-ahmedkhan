"""Shared helpers for Celery notification tasks."""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.logging import get_correlation_id, get_request_id
from app.core.metrics import record_celery_task
from app.db import SessionLocal
from app.services.failed_job_service import FailedJobService

logger = logging.getLogger(__name__)


def run_notification_task(
    task,
    *,
    appointment_id: int,
    metric_name: str,
    handler: Callable[[Session], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a notification handler with shared logging, retries, and failure recording."""
    correlation_id = get_correlation_id()
    request_id = get_request_id()
    task_start_time = time.time()
    task_success = False

    logger.info(
        "Starting notification task",
        extra={
            "task_id": task.request.id,
            "task_name": task.name,
            "appointment_id": appointment_id,
            "correlation_id": correlation_id,
            "request_id": request_id,
        },
    )

    db = SessionLocal()
    try:
        result = handler(db)
        task_success = True
        logger.info(
            "Notification task completed successfully",
            extra={
                "task_id": task.request.id,
                "appointment_id": appointment_id,
                "correlation_id": correlation_id,
            },
        )
        return result
    except AppError as exc:
        logger.error(
            "Notification task failed with AppError",
            extra={
                "task_id": task.request.id,
                "appointment_id": appointment_id,
                "correlation_id": correlation_id,
                "error": str(exc),
            },
            exc_info=True,
        )
        FailedJobService(db).record_failure(
            task_name=task.name,
            task_id=task.request.id,
            exc=exc,
            payload={"appointment_id": appointment_id},
            traceback_text=traceback.format_exc(),
        )
        raise
    except Exception as exc:
        logger.error(
            "Notification task failed with exception",
            extra={
                "task_id": task.request.id,
                "appointment_id": appointment_id,
                "correlation_id": correlation_id,
                "error": str(exc),
            },
            exc_info=True,
        )
        if isinstance(exc, (ConnectionError, TimeoutError)) and task.request.retries < task.max_retries:
            logger.info(
                "Retrying notification task",
                extra={
                    "task_id": task.request.id,
                    "appointment_id": appointment_id,
                    "retry_count": task.request.retries,
                },
            )
            raise task.retry(exc=exc, countdown=30)
        FailedJobService(db).record_failure(
            task_name=task.name,
            task_id=task.request.id,
            exc=exc,
            payload={"appointment_id": appointment_id},
            traceback_text=traceback.format_exc(),
        )
        raise
    finally:
        db.close()
        try:
            record_celery_task(
                task_name=metric_name,
                success=task_success,
                duration_seconds=time.time() - task_start_time,
            )
        except Exception as metric_exc:
            logger.error("Failed to record Celery task metric: %s", metric_exc, exc_info=True)
