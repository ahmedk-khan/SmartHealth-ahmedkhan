from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def generate_request_id() -> str:
    return uuid.uuid4().hex

_PHI_KEYWORDS = (
    "name",
    "email",
    "phone",
    "mobile",
    "dob",
    "date_of_birth",
    "address",
    "street",
    "city",
    "postal_code",
    "ssn",
    "diagnosis",
    "symptoms",
    "notes",
    "medical_history",
    "insurance",
    "allergies",
    "patient_name",
    "provider_name",
)


def set_correlation_id(value: str | None):
    if value is None:
        return None
    return _CORRELATION_ID.set(value)


def get_correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def reset_correlation_id(token):
    if token is not None:
        _CORRELATION_ID.reset(token)


def set_request_id(value: str | None):
    if value is None:
        return None
    return _REQUEST_ID.set(value)


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


def reset_request_id(token):
    if token is not None:
        _REQUEST_ID.reset(token)


def build_correlation_headers(*, correlation_id: str | None = None, request_id: str | None = None) -> dict[str, str]:
    resolved_correlation_id = correlation_id or get_correlation_id()
    resolved_request_id = request_id or get_request_id() or resolved_correlation_id
    headers: dict[str, str] = {}
    if resolved_correlation_id:
        headers["X-Correlation-ID"] = resolved_correlation_id
    if resolved_request_id:
        headers["X-Request-ID"] = resolved_request_id
    return headers


def _is_phi_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(token in lowered for token in _PHI_KEYWORDS) or lowered.endswith("_name")


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_phi_key(str(key)):
                continue
            cleaned[str(key)] = sanitize_for_json(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, set):
        return [sanitize_for_json(item) for item in sorted(value, key=str)]
    if isinstance(value, str):
        lowered = value.lower()
        if any(token in lowered for token in _PHI_KEYWORDS):
            return "[REDACTED]"
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_for_json(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "correlation_id",
                "request_id",
            }:
                continue
            if key.startswith("_"):
                continue
            payload[key] = sanitize_for_json(value)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure structured JSON logging globally for all loggers.
    
    This ensures all log output is in JSON format with correlation ID and request ID
    propagated from context variables.
    
    Args:
        level: Logging level (default: logging.INFO)
    """
    formatter = JSONFormatter()
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add stream handler with JSON formatter
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)
    
    # Configure uvicorn access logging
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(level)
    for handler in access_logger.handlers[:]:
        access_logger.removeHandler(handler)
    access_handler = logging.StreamHandler()
    access_handler.setFormatter(formatter)
    access_logger.addHandler(access_handler)
