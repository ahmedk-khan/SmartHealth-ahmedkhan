"""Shared helpers for mapping domain errors to Temporal activity failures."""

from temporalio.exceptions import ApplicationError

from app.core.exceptions import AppError


def to_non_retryable_application_error(exc: AppError) -> ApplicationError:
    """Convert an AppError into a non-retryable Temporal ApplicationError."""
    return ApplicationError(exc.message, type=exc.error_type, non_retryable=True)
