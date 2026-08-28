from typing import Any
import logging

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from app.core.logging import generate_request_id


logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_type: str = "app_error",
        detail: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.detail = detail


def app_error(message: str, status_code: int = 400, error_type: str = "app_error", detail: Any = None) -> AppError:
    return AppError(message=message, status_code=status_code, error_type=error_type, detail=detail)


def forbidden_error(message: str = "Forbidden", detail: Any = None) -> AppError:
    return app_error(message, status_code=403, error_type="forbidden", detail=detail)


def not_found_error(message: str = "Not found", detail: Any = None) -> AppError:
    return app_error(message, status_code=404, error_type="not_found", detail=detail)


def conflict_error(message: str = "Conflict", detail: Any = None) -> AppError:
    return app_error(message, status_code=409, error_type="conflict", detail=detail)


def validation_error(message: str = "Validation failed", detail: Any = None) -> AppError:
    return app_error(message, status_code=422, error_type="validation_error", detail=detail)


def invalid_token_error(message: str = "Could not validate credentials", detail: Any = None) -> AppError:
    return app_error(message, status_code=401, error_type="invalid_token", detail=detail)


def format_app_error(exc: AppError) -> dict:
    return {
        "error": {
            "type": exc.error_type,
            "message": exc.message,
            "detail": exc.detail,
        }
    }


def format_error_payload(error_type: str, message: str, detail: Any = None, request_id: str | None = None) -> dict:
    payload = {
        "error": {
            "type": error_type,
            "message": message,
            "detail": detail,
        }
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=exc.status_code, content={**format_app_error(exc), **({"request_id": request_id} if request_id else {})})


def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=429,
        content=format_error_payload("rate_limit_exceeded", "Rate limit exceeded", request_id=request_id),
    )


def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=422,
        content=format_error_payload("validation_error", "Request validation failed", jsonable_encoder(exc.errors()), request_id=request_id),
    )


def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", None)
    headers = getattr(exc, "headers", None)
    message = detail if isinstance(detail, str) else "Request failed"
    return JSONResponse(
        status_code=status_code,
        content=format_error_payload("http_error", message, detail, request_id=request_id),
        headers=headers,
    )


def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=format_error_payload("internal_error", "Internal server error", None, request_id=request_id),
    )


