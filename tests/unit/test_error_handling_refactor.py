import pytest
from fastapi import FastAPI, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import logging
import uuid

from app.core.exceptions import (
    AppError,
    NotFoundError,
    ProviderNotFoundError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
    ValidationError,
    ExternalServiceError,
    app_error_handler,
    validation_exception_handler,
    database_exception_handler,
    unexpected_exception_handler,
)
from app.core.middleware import CorrelationIdMiddleware


# Setup dummy app to test exception handlers and middleware in isolation
app = FastAPI()
app.add_middleware(CorrelationIdMiddleware)

# Register handlers exactly as app_factory does
app.exception_handler(AppError)(app_error_handler)
app.exception_handler(RequestValidationError)(validation_exception_handler)
app.exception_handler(SQLAlchemyError)(database_exception_handler)
app.exception_handler(Exception)(unexpected_exception_handler)


@app.get("/error/not-found")
def route_not_found():
    raise ProviderNotFoundError("Provider profile is missing")


@app.get("/error/conflict")
def route_conflict():
    raise ConflictError("Slot has been booked", code="SLOT_BOOKED")


@app.get("/error/unauthorized")
def route_unauthorized():
    raise UnauthorizedError("No authorization credentials supplied", code="AUTH_REQUIRED")


@app.get("/error/forbidden")
def route_forbidden():
    raise ForbiddenError("You lack admin privilege")


@app.get("/error/validation")
def route_validation():
    raise ValidationError("Required field missing", code="FIELD_MISSING")


@app.get("/error/external")
def route_external():
    raise ExternalServiceError("Gateway timeout from Temporal", status_code=504)


@app.get("/error/database")
def route_database():
    raise SQLAlchemyError("SELECT * FROM sensitive_table; Column admin_pwd does not exist")


@app.get("/error/integrity")
def route_integrity():
    raise IntegrityError("INSERT INTO departments (name) VALUES ('Cardiology')", {}, Exception("duplicate key value violates unique constraint"))


@app.get("/error/unexpected")
def route_unexpected():
    raise ZeroDivisionError("division by zero")


@app.post("/error/pydantic")
def route_pydantic(data: dict):
    # Triggers RequestValidationError if type mismatches or schema validation fails
    return data


client = TestClient(app, raise_server_exceptions=False)


def test_standard_custom_errors_payload_nesting():
    # 1. NotFoundError (ProviderNotFoundError)
    response = client.get("/error/not-found")
    assert response.status_code == 404
    payload = response.json()
    assert "error" in payload
    err = payload["error"]
    assert err["type"] == "not_found"
    assert err["message"] == "Provider profile is missing"
    assert err["code"] == "PROVIDER_NOT_FOUND"
    assert "request_id" in err
    assert "-" in err["request_id"]  # verify uuid formatting has hyphens

    # 2. ConflictError
    response = client.get("/error/conflict")
    assert response.status_code == 409
    err = response.json()["error"]
    assert err["type"] == "conflict"
    assert err["message"] == "Slot has been booked"
    assert err["code"] == "SLOT_BOOKED"

    # 3. UnauthorizedError
    response = client.get("/error/unauthorized")
    assert response.status_code == 401
    err = response.json()["error"]
    assert err["type"] == "unauthorized"
    assert err["code"] == "AUTH_REQUIRED"

    # 4. ForbiddenError
    response = client.get("/error/forbidden")
    assert response.status_code == 403
    err = response.json()["error"]
    assert err["type"] == "forbidden"
    assert err["code"] == "FORBIDDEN"

    # 5. ValidationError
    response = client.get("/error/validation")
    assert response.status_code == 422
    err = response.json()["error"]
    assert err["type"] == "validation_error"
    assert err["code"] == "FIELD_MISSING"

    # 6. ExternalServiceError
    response = client.get("/error/external")
    assert response.status_code == 504
    err = response.json()["error"]
    assert err["type"] == "external_service_error"
    assert err["code"] == "EXTERNAL_SERVICE_ERROR"


def test_database_exception_masking(caplog):
    with caplog.at_level(logging.ERROR):
        response = client.get("/error/database")
    
    assert response.status_code == 500
    payload = response.json()
    assert "error" in payload
    err = payload["error"]
    assert err["type"] == "internal_error"
    assert err["message"] == "An unexpected error occurred"
    assert err["code"] == "INTERNAL_ERROR"
    assert "request_id" in err
    
    # Assert database details are masked and not returned in JSON
    assert "sensitive_table" not in response.text
    assert "SQL" not in response.text

    # Assert server logs contain the real database error and details
    assert "Database exception occurred" in caplog.text
    assert "sensitive_table" in caplog.text


def test_integrity_error_returns_conflict(caplog):
    with caplog.at_level(logging.ERROR):
        response = client.get("/error/integrity")

    assert response.status_code == 409
    err = response.json()["error"]
    assert err["type"] == "conflict"
    assert err["message"] == "Resource already exists"
    assert err["code"] == "RESOURCE_ALREADY_EXISTS"
    assert "request_id" in err
    assert "duplicate key value violates unique constraint" in caplog.text


def test_unexpected_exception_masking(caplog):
    with caplog.at_level(logging.ERROR):
        response = client.get("/error/unexpected")

    assert response.status_code == 500
    err = response.json()["error"]
    assert err["type"] == "internal_error"
    assert err["message"] == "An unexpected error occurred"
    assert err["code"] == "INTERNAL_ERROR"

    # Assert raw exception trace details are shielded
    assert "ZeroDivisionError" not in response.text
    assert "division by zero" not in response.text

    # Assert server logs contain division by zero exception trace
    assert "Unhandled exception for" in caplog.text
    assert "ZeroDivisionError" in caplog.text


def test_request_validation_error_nesting():
    # Pass invalid type/payload to trigger validation error
    response = client.post("/error/pydantic", data="invalid payload format")
    assert response.status_code == 422
    payload = response.json()
    assert "error" in payload
    err = payload["error"]
    assert err["type"] == "validation_error"
    assert err["message"] == "Request validation failed"
    assert err["code"] == "VALIDATION_FAILED"
    assert "detail" in err
    assert "request_id" in err


def test_correlation_id_middleware_and_header_propagation():
    custom_correlation_id = str(uuid.uuid4())
    custom_request_id = str(uuid.uuid4())
    
    response = client.get(
        "/error/validation",
        headers={
            "X-Correlation-ID": custom_correlation_id,
            "X-Request-ID": custom_request_id,
        }
    )
    
    # Assert headers are echoed back
    assert response.headers.get("X-Correlation-ID") == custom_correlation_id
    assert response.headers.get("X-Request-ID") == custom_request_id

    # Assert that request ID is nested in the error block
    err = response.json()["error"]
    assert err["request_id"] == custom_request_id
