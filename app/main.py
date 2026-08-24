from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api import api_router
from app.api.metrics_endpoint import create_metrics_endpoint
from app.core.exceptions import AppError, app_error_handler, generate_request_id, http_exception_handler, unexpected_exception_handler, validation_exception_handler
from app.core.logging import set_correlation_id, set_request_id, reset_correlation_id, reset_request_id, get_correlation_id, configure_logging
from app.core.http_metrics_middleware import HTTPMetricsMiddleware
from app.db import init_db


logger = logging.getLogger(__name__)

# Configure structured JSON logging
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SmartHealth API",
    version="1.0.0",
    description=(
        "SmartHealth is a healthcare scheduling and operations API for patient, provider, "
        "appointment, and service workflows. The documented endpoints include authentication, "
        "appointments, services, departments, providers, slots, tasks, and analytics."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={"persistAuthorization": True},
    contact={"name": "SmartHealth Team", "email": "support@smarthealth.example"},
    license_info={"name": "MIT License"},
    lifespan=lifespan,
)

app.openapi_tags = [
    {"name": "health", "description": "Health and readiness checks for the service."},
    {"name": "auth", "description": "Authentication and user identity flows."},
    {"name": "appointments", "description": "Appointment booking, cancellation, rescheduling, and visit-flow operations."},
    {"name": "services", "description": "Service catalog management and publication workflows."},
    {"name": "slots", "description": "Slot availability and reservation operations."},
    {"name": "providers", "description": "Provider profiles and provider-specific schedules."},
    {"name": "patients", "description": "Patient profiles and patient-related lookup endpoints."},
    {"name": "departments", "description": "Department catalog and organization metadata."},
    {"name": "tasks", "description": "Background task status and operational lookup endpoints."},
    {"name": "analytics", "description": "Operational and analytics summaries for reporting."},
    {"name": "public", "description": "Public-facing catalog endpoints available without authenticated access."},
    {"name": "search", "description": "Authenticated semantic search over published service content."},
]


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to extract/generate correlation ID and request ID, and set them in context variables."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate correlation ID (should persist across a user/workflow)
        correlation_id = request.headers.get("X-Correlation-ID") or generate_request_id()
        
        # Extract or generate request ID (specific to this HTTP request)
        request_id = request.headers.get("X-Request-ID") or generate_request_id()
        
        # Store in request state for access in route handlers
        request.state.correlation_id = correlation_id
        request.state.request_id = request_id
        
        # Set context variables for logging and downstream tasks
        correlation_token = set_correlation_id(correlation_id)
        request_token = set_request_id(request_id)
        
        try:
            response = await call_next(request)
        finally:
            # Clean up context variables
            reset_correlation_id(correlation_token)
            reset_request_id(request_token)
        
        # Add correlation ID and request ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(HTTPMetricsMiddleware)


app.exception_handler(AppError)(app_error_handler)
app.exception_handler(RequestValidationError)(validation_exception_handler)
app.exception_handler(HTTPException)(http_exception_handler)
app.exception_handler(Exception)(unexpected_exception_handler)


@app.get("/", tags=["health"], summary="Service status", description="Returns a simple readiness signal to confirm the API is running.")
def root():
    return {"message": "app api is running"}


@app.get("/metrics", tags=["health"], summary="Prometheus metrics", description="Exposes Prometheus-formatted runtime metrics for scraping and monitoring.")
async def metrics():
    """Prometheus metrics endpoint."""
    metrics_handler = create_metrics_endpoint()
    return await metrics_handler()


app.include_router(api_router)
