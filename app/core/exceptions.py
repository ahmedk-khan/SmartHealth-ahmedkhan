from typing import Any
import logging

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.core.logging import get_request_id


logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base exception for all application errors."""
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_type: str = "app_error",
        code: str | None = None,
        detail: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.code = code or error_type.upper()
        self.detail = detail


class NotFoundError(AppError):
    """Exception raised when a resource is not found."""
    def __init__(self, message: str = "Not found", code: str = "NOT_FOUND", detail: Any = None):
        super().__init__(
            message=message,
            status_code=404,
            error_type="not_found",
            code=code,
            detail=detail,
        )


class ProviderNotFoundError(NotFoundError):
    """Exception raised when a provider is not found."""
    def __init__(self, message: str = "Provider not found", detail: Any = None):
        super().__init__(message=message, code="PROVIDER_NOT_FOUND", detail=detail)


class AppointmentNotFoundError(NotFoundError):
    """Exception raised when an appointment is not found."""
    def __init__(self, message: str = "Appointment not found", detail: Any = None):
        super().__init__(message=message, code="APPOINTMENT_NOT_FOUND", detail=detail)


class PatientNotFoundError(NotFoundError):
    """Exception raised when a patient is not found."""
    def __init__(self, message: str = "Patient not found", detail: Any = None):
        super().__init__(message=message, code="PATIENT_NOT_FOUND", detail=detail)


class SlotNotFoundError(NotFoundError):
    """Exception raised when a slot is not found."""
    def __init__(self, message: str = "Slot not found", detail: Any = None):
        super().__init__(message=message, code="SLOT_NOT_FOUND", detail=detail)


class DepartmentNotFoundError(NotFoundError):
    """Exception raised when a department is not found."""
    def __init__(self, message: str = "Department not found", detail: Any = None):
        super().__init__(message=message, code="DEPARTMENT_NOT_FOUND", detail=detail)


class ConflictError(AppError):
    """Exception raised for resource conflicts / invalid state transitions."""
    def __init__(self, message: str = "Conflict", code: str = "CONFLICT", detail: Any = None):
        super().__init__(
            message=message,
            status_code=409,
            error_type="conflict",
            code=code,
            detail=detail,
        )


class ForbiddenError(AppError):
    """Exception raised when an action is forbidden."""
    def __init__(self, message: str = "Forbidden", code: str = "FORBIDDEN", detail: Any = None):
        super().__init__(
            message=message,
            status_code=403,
            error_type="forbidden",
            code=code,
            detail=detail,
        )


class UnauthorizedError(AppError):
    """Exception raised for authentication failures."""
    def __init__(self, message: str = "Unauthorized", code: str = "UNAUTHORIZED", detail: Any = None):
        super().__init__(
            message=message,
            status_code=401,
            error_type="unauthorized",
            code=code,
            detail=detail,
        )


class ValidationError(AppError):
    """Exception raised for application-level validation errors."""
    def __init__(self, message: str = "Validation failed", code: str = "VALIDATION_FAILED", detail: Any = None):
        super().__init__(
            message=message,
            status_code=422,
            error_type="validation_error",
            code=code,
            detail=detail,
        )


class ExternalServiceError(AppError):
    """Exception raised when an external dependency/service call fails."""
    def __init__(
        self,
        message: str = "External service error",
        status_code: int = 502,
        code: str = "EXTERNAL_SERVICE_ERROR",
        detail: Any = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code,
            error_type="external_service_error",
            code=code,
            detail=detail,
        )


def format_error_payload(
    error_type: str,
    message: str,
    code: str,
    detail: Any = None,
    request_id: str | None = None,
) -> dict:
    payload = {
        "error": {
            "type": error_type,
            "message": message,
            "code": code,
        }
    }
    if detail is not None:
        payload["error"]["detail"] = detail
    if request_id is not None:
        payload["error"]["request_id"] = request_id
    return payload


def format_app_error(exc: AppError, request_id: str | None = None) -> dict:
    return format_error_payload(
        error_type=exc.error_type,
        message=exc.message,
        code=exc.code,
        detail=exc.detail,
        request_id=request_id,
    )


def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    return JSONResponse(
        status_code=exc.status_code,
        content=format_app_error(exc, request_id=request_id),
    )


def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    return JSONResponse(
        status_code=429,
        content=format_error_payload(
            error_type="rate_limit_exceeded",
            message="Rate limit exceeded",
            code="RATE_LIMIT_EXCEEDED",
            detail=None,
            request_id=request_id,
        ),
    )


def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    return JSONResponse(
        status_code=422,
        content=format_error_payload(
            error_type="validation_error",
            message="Request validation failed",
            code="VALIDATION_FAILED",
            detail=jsonable_encoder(exc.errors()),
            request_id=request_id,
        ),
    )


def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", None)
    headers = getattr(exc, "headers", None)
    message = detail if isinstance(detail, str) else "Request failed"
    # Resolve appropriate code
    code = "HTTP_ERROR"
    if status_code == 401:
        code = "UNAUTHORIZED"
    elif status_code == 403:
        code = "FORBIDDEN"
    elif status_code == 404:
        code = "NOT_FOUND"
    return JSONResponse(
        status_code=status_code,
        content=format_error_payload(
            error_type="http_error",
            message=message,
            code=code,
            detail=detail if detail != message else None,
            request_id=request_id,
        ),
        headers=headers,
    )


def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    logger.exception(
        "Database exception occurred for %s %s [Request ID: %s]",
        request.method,
        request.url.path,
        request_id,
        exc_info=exc,
    )

    if isinstance(exc, IntegrityError):
        return JSONResponse(
            status_code=409,
            content=format_error_payload(
                error_type="conflict",
                message="Resource already exists",
                code="RESOURCE_ALREADY_EXISTS",
                detail=None,
                request_id=request_id,
            ),
        )

    return JSONResponse(
        status_code=500,
        content=format_error_payload(
            error_type="internal_error",
            message="An unexpected error occurred",
            code="INTERNAL_ERROR",
            detail=None,
            request_id=request_id,
        ),
    )


def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    logger.exception(
        "Unhandled exception for %s %s [Request ID: %s]",
        request.method,
        request.url.path,
        request_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content=format_error_payload(
            error_type="internal_error",
            message="An unexpected error occurred",
            code="INTERNAL_ERROR",
            detail=None,
            request_id=request_id,
        ),
    )
