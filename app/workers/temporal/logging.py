"""
Utilities for structured logging in Temporal workflows and activities.

Ensures correlation IDs and request IDs are propagated through Temporal's
execution context and included in all log output.
"""

import logging
from typing import Any, Optional

from app.core.logging import set_correlation_id, set_request_id, get_correlation_id, get_request_id


logger = logging.getLogger(__name__)


def extract_correlation_context(activity_input: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """
    Extract correlation ID and request ID from activity input.
    
    Args:
        activity_input: Dictionary containing activity parameters
        
    Returns:
        Tuple of (correlation_id, request_id)
    """
    correlation_id = activity_input.get("correlation_id")
    request_id = activity_input.get("request_id")
    return correlation_id, request_id


def setup_activity_context(activity_input: dict[str, Any], activity_name: str) -> None:
    """
    Set up correlation context for an activity.
    
    This should be called at the start of each activity to ensure
    correlation IDs are available in logging context.
    
    Args:
        activity_input: Dictionary containing activity parameters
        activity_name: Name of the activity for logging
    """
    correlation_id, request_id = extract_correlation_context(activity_input)
    
    if correlation_id:
        set_correlation_id(correlation_id)
    if request_id:
        set_request_id(request_id)
    
    logger.info(
        f"Activity '{activity_name}' started",
        extra={
            "activity_name": activity_name,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
    )


def log_activity_step(step_name: str, data: Optional[dict[str, Any]] = None) -> None:
    """
    Log a step within an activity with correlation context.
    
    Args:
        step_name: Name of the step being executed
        data: Optional data to include in the log
    """
    logger.info(
        f"Activity step: {step_name}",
        extra={
            "activity_step": step_name,
            **(data or {})
        }
    )


def log_activity_error(
    activity_name: str,
    error: Exception,
    context: Optional[dict[str, Any]] = None
) -> None:
    """
    Log an activity error with correlation context.
    
    Args:
        activity_name: Name of the activity
        error: The exception that occurred
        context: Optional additional context
    """
    logger.error(
        f"Activity '{activity_name}' failed",
        extra={
            "activity_name": activity_name,
            "error": str(error),
            **(context or {})
        },
        exc_info=True
    )
