"""Temporal activity logging utilities with correlation context.

These functions set up and maintain correlation context (correlation_id, request_id)
across activity invocations, enabling end-to-end tracing through workflows.
"""

import logging
from typing import Any

from app.core.exceptions import AppError
from app.core.logging import set_correlation_id, set_request_id, get_correlation_id, get_request_id

logger = logging.getLogger(__name__)


def setup_activity_context(activity_data: dict[str, Any], activity_name: str) -> None:
    """Set up correlation context for a Temporal activity.
    
    Extracts correlation_id and request_id from activity_data and sets them as
    context variables so all logging within the activity includes these IDs.
    
    Args:
        activity_data: Dictionary containing activity input, may include
            correlation_id and request_id from the workflow
        activity_name: Name of the activity for logging purposes
    """
    correlation_id = activity_data.get("correlation_id")
    request_id = activity_data.get("request_id")
    
    if correlation_id:
        set_correlation_id(correlation_id)
    if request_id:
        set_request_id(request_id)
    
    logger.info(
        f"Activity started: {activity_name}",
        extra={
            "activity_name": activity_name,
            "correlation_id": get_correlation_id(),
            "request_id": get_request_id(),
        }
    )


def log_activity_step(message: str, data: dict[str, Any] | None = None) -> None:
    """Log a step within a Temporal activity.
    
    Logs structured information about activity progress, automatically including
    correlation context for tracing.
    
    Args:
        message: Description of the activity step
        data: Optional dictionary of structured data to include in the log
    """
    log_data = data or {}
    log_data.update({
        "correlation_id": get_correlation_id(),
        "request_id": get_request_id(),
    })
    
    logger.info(message, extra=log_data)


def log_activity_error(activity_name: str, error: Exception) -> None:
    """Log an error within a Temporal activity.
    
    Logs error details with correlation context for debugging and audit purposes.
    
    Args:
        activity_name: Name of the activity that failed
        error: The exception that occurred
    """
    error_details = {
        "activity_name": activity_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "correlation_id": get_correlation_id(),
        "request_id": get_request_id(),
    }
    
    if isinstance(error, AppError):
        error_details["error_code"] = error.code
    
    logger.error(
        f"Activity error in {activity_name}: {str(error)}",
        extra=error_details,
        exc_info=True
    )
