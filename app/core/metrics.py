"""
Prometheus metrics for SmartHealth application.

Provides structured metrics for HTTP operations and domain-specific events
with proper exception handling and thread safety.
"""

from enum import Enum
from typing import Optional

from prometheus_client import Counter, Histogram, Gauge


class HTTPMethod(str, Enum):
    """HTTP request methods."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


# ============================================================================
# HTTP Metrics
# ============================================================================

http_request_count = Counter(
    "http_request_total",
    "Total HTTP requests by method, status, and endpoint",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds by method and endpoint",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

http_exceptions_total = Counter(
    "http_exceptions_total",
    "Total HTTP exceptions by type and endpoint",
    ["exception_type", "endpoint"],
)

http_response_size_bytes = Histogram(
    "http_response_size_bytes",
    "HTTP response size in bytes by method and endpoint",
    ["method", "endpoint"],
    buckets=(100, 1000, 10000, 100000, 1000000),
)

# ============================================================================
# Domain Metrics: Appointments
# ============================================================================

appointments_created_total = Counter(
    "appointments_created_total",
    "Total appointments created",
)

appointments_cancelled_total = Counter(
    "appointments_cancelled_total",
    "Total appointments cancelled",
)

appointments_by_status = Gauge(
    "appointments_by_status",
    "Current count of appointments by status",
    ["status"],
)

appointments_visit_status_transitions_total = Counter(
    "appointments_visit_status_transitions_total",
    "Total appointment visit status transitions by from_status and to_status",
    ["from_status", "to_status"],
)

appointment_booking_duration_seconds = Histogram(
    "appointment_booking_duration_seconds",
    "Time to complete appointment booking workflow",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# ============================================================================
# Domain Metrics: Services
# ============================================================================

services_published_total = Counter(
    "services_published_total",
    "Total services published",
)

services_active_total = Gauge(
    "services_active_total",
    "Current count of active services",
)

services_by_department = Gauge(
    "services_by_department",
    "Count of services by department",
    ["department"],
)

# ============================================================================
# Domain Metrics: Billing
# ============================================================================

billing_records_created_total = Counter(
    "billing_records_created_total",
    "Total billing records created",
)

billing_total_amount = Gauge(
    "billing_total_amount",
    "Total billing amount in system by status",
    ["status"],
)

billing_by_status = Gauge(
    "billing_by_status",
    "Count of billing records by status",
    ["status"],
)

# ============================================================================
# Domain Metrics: Authentication
# ============================================================================

login_attempts_total = Counter(
    "login_attempts_total",
    "Total login attempts by status",
    ["status"],
)

user_registrations_total = Counter(
    "user_registrations_total",
    "Total user registrations by role",
    ["role"],
)

active_sessions = Gauge(
    "active_sessions",
    "Current number of active sessions",
)

# ============================================================================
# Domain Metrics: Async Tasks
# ============================================================================

celery_task_executions_total = Counter(
    "celery_task_executions_total",
    "Total Celery task executions by task_name and status",
    ["task_name", "status"],
)

celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration in seconds by task_name",
    ["task_name"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# ============================================================================
# AI Metrics
# ============================================================================

ai_requests_total = Counter("ai_requests_total", "AI interactions by intent and outcome", ["intent", "outcome"])
ai_refusals_total = Counter("ai_refusals_total", "AI safety refusals", ["intent"])
ai_cache_hits_total = Counter("ai_cache_hits_total", "AI answer cache hits")
ai_request_duration_seconds = Histogram("ai_request_duration_seconds", "AI interaction latency", ["intent"])
ai_input_tokens_total = Counter("ai_input_tokens_total", "Estimated AI input tokens", ["intent"])
ai_output_tokens_total = Counter("ai_output_tokens_total", "Estimated AI output tokens", ["intent"])
ai_booking_conversions = Gauge("ai_booking_conversions", "Bookings associated with AI appointment navigation")
ai_booking_conversion_rate = Gauge("ai_booking_conversion_rate", "Appointment conversion rate from AI appointment navigation")


def record_ai_interaction(intent: str, outcome: str, latency_seconds: float, input_tokens: int, output_tokens: int, refused: bool) -> None:
    try:
        ai_requests_total.labels(intent=intent, outcome=outcome).inc()
        ai_request_duration_seconds.labels(intent=intent).observe(latency_seconds)
        ai_input_tokens_total.labels(intent=intent).inc(input_tokens)
        ai_output_tokens_total.labels(intent=intent).inc(output_tokens)
        if refused:
            ai_refusals_total.labels(intent=intent).inc()
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to record AI metrics", exc_info=True)


def record_ai_cache_hit() -> None:
    try:
        ai_cache_hits_total.inc()
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to record AI cache metric", exc_info=True)


def set_ai_booking_conversions(value: int) -> None:
    try:
        ai_booking_conversions.set(value)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to record AI booking conversion count", exc_info=True)


def set_ai_booking_conversion_rate(value: float) -> None:
    try:
        ai_booking_conversion_rate.set(value)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to record AI booking conversion rate", exc_info=True)

# ============================================================================
# Utility Functions
# ============================================================================


def record_http_request(
    method: str,
    endpoint: str,
    status: int,
    duration_seconds: float,
    response_size_bytes: Optional[int] = None,
) -> None:
    """
    Record HTTP request metrics.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: Request endpoint/path
        status: HTTP status code
        duration_seconds: Request duration in seconds
        response_size_bytes: Optional response size in bytes
    """
    try:
        http_request_count.labels(method=method, endpoint=endpoint, status=status).inc()
        http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(
            duration_seconds
        )
        if response_size_bytes is not None:
            http_response_size_bytes.labels(method=method, endpoint=endpoint).observe(
                response_size_bytes
            )
    except Exception as exc:
        # Log but don't raise to avoid breaking request handling
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record HTTP metrics: {exc}", exc_info=True)


def record_http_exception(exception_type: str, endpoint: str) -> None:
    """
    Record HTTP exception metrics.
    
    Args:
        exception_type: Type of exception
        endpoint: Request endpoint
    """
    try:
        http_exceptions_total.labels(exception_type=exception_type, endpoint=endpoint).inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record exception metric: {exc}", exc_info=True)


def record_appointment_created() -> None:
    """Record appointment creation event."""
    try:
        appointments_created_total.inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record appointment creation metric: {exc}", exc_info=True)


def record_appointment_cancelled() -> None:
    """Record appointment cancellation event."""
    try:
        appointments_cancelled_total.inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record appointment cancellation metric: {exc}", exc_info=True)


def set_appointments_by_status(status: str, count: int) -> None:
    """
    Set gauge for appointments by status.
    
    Args:
        status: Appointment status
        count: Current count
    """
    try:
        appointments_by_status.labels(status=status).set(count)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to set appointments status gauge: {exc}", exc_info=True)


def record_visit_status_transition(from_status: str, to_status: str) -> None:
    """
    Record visit status transition.
    
    Args:
        from_status: Previous status
        to_status: New status
    """
    try:
        appointments_visit_status_transitions_total.labels(
            from_status=from_status, to_status=to_status
        ).inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record visit status transition metric: {exc}", exc_info=True)


def record_appointment_booking_time(duration_seconds: float) -> None:
    """
    Record appointment booking workflow duration.
    
    Args:
        duration_seconds: Time taken to complete booking
    """
    try:
        appointment_booking_duration_seconds.observe(duration_seconds)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record booking time metric: {exc}", exc_info=True)


def record_service_published() -> None:
    """Record service publication event."""
    try:
        services_published_total.inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record service published metric: {exc}", exc_info=True)


def set_active_services(count: int) -> None:
    """
    Set gauge for active services.
    
    Args:
        count: Current count of active services
    """
    try:
        services_active_total.set(count)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to set active services gauge: {exc}", exc_info=True)


def set_services_by_department(department: str, count: int) -> None:
    """
    Set gauge for services by department.
    
    Args:
        department: Department name
        count: Count of services in department
    """
    try:
        services_by_department.labels(department=department).set(count)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to set services by department gauge: {exc}", exc_info=True)


def record_billing_created() -> None:
    """Record billing record creation."""
    try:
        billing_records_created_total.inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record billing creation metric: {exc}", exc_info=True)


def set_billing_total_amount(status: str, amount: float) -> None:
    """
    Set gauge for total billing amount by status.
    
    Args:
        status: Billing status
        amount: Total amount
    """
    try:
        billing_total_amount.labels(status=status).set(amount)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to set billing amount gauge: {exc}", exc_info=True)


def set_billing_by_status(status: str, count: int) -> None:
    """
    Set gauge for billing records by status.
    
    Args:
        status: Billing status
        count: Count of records
    """
    try:
        billing_by_status.labels(status=status).set(count)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to set billing status gauge: {exc}", exc_info=True)


def record_login_attempt(success: bool) -> None:
    """
    Record login attempt.
    
    Args:
        success: Whether login was successful
    """
    try:
        status = "success" if success else "failure"
        login_attempts_total.labels(status=status).inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record login attempt metric: {exc}", exc_info=True)


def record_user_registration(role: str) -> None:
    """
    Record user registration.
    
    Args:
        role: User role
    """
    try:
        user_registrations_total.labels(role=role).inc()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record registration metric: {exc}", exc_info=True)


def set_active_sessions_count(count: int) -> None:
    """
    Set gauge for active sessions.
    
    Args:
        count: Current number of active sessions
    """
    try:
        active_sessions.set(count)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to set active sessions gauge: {exc}", exc_info=True)


def record_celery_task(task_name: str, success: bool, duration_seconds: float) -> None:
    """
    Record Celery task execution.
    
    Args:
        task_name: Name of the task
        success: Whether task succeeded
        duration_seconds: Task execution duration
    """
    try:
        status = "success" if success else "failure"
        celery_task_executions_total.labels(task_name=task_name, status=status).inc()
        celery_task_duration_seconds.labels(task_name=task_name).observe(duration_seconds)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to record Celery task metric: {exc}", exc_info=True)
