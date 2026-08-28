from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from slowapi.errors import RateLimitExceeded
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from app.api import api_router
from app.api.v1.endpoints.metrics import create_metrics_endpoint
from app.core.settings import settings
from app.db import engine
from app.core.exceptions import AppError, app_error_handler, http_exception_handler, rate_limit_exception_handler, unexpected_exception_handler, validation_exception_handler
from app.core.http_metrics_middleware import HTTPMetricsMiddleware
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware
from app.core.rate_limit import limiter
from app.core.security_headers import SecurityHeadersMiddleware

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

try:
    from kafka import KafkaProducer
except ImportError:  # pragma: no cover
    KafkaProducer = None


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        redis_client = None
        kafka_producer = None
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))

            if settings.app_env.lower() in {"production", "prod"}:
                if redis is None:
                    raise RuntimeError("Redis client is not installed")
                redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                redis_client.ping()

            if settings.kafka_enabled:
                if KafkaProducer is None:
                    raise RuntimeError("Kafka client is not installed")
                kafka_producer = KafkaProducer(
                    bootstrap_servers=settings.kafka_bootstrap_servers,
                    api_version_auto_timeout_ms=3000,
                    request_timeout_ms=3000,
                )
                if not kafka_producer.bootstrap_connected():
                    raise RuntimeError("Kafka broker is not available")

            app.state.redis_client = redis_client
            app.state.kafka_producer = kafka_producer
            yield
        finally:
            if kafka_producer is not None:
                kafka_producer.close(timeout=3)
            if redis_client is not None:
                redis_client.close()
            engine.dispose()

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
    app.state.limiter = limiter
    app.state.app_env = settings.app_env.lower()

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

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(HTTPMetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.app_env.lower() in {"production", "prod"}:
        app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.exception_handler(AppError)(app_error_handler)
    app.exception_handler(RateLimitExceeded)(rate_limit_exception_handler)
    app.exception_handler(RequestValidationError)(validation_exception_handler)
    app.exception_handler(HTTPException)(http_exception_handler)
    app.exception_handler(Exception)(unexpected_exception_handler)

    @app.get("/", tags=["health"], summary="Service status", description="Returns a simple readiness signal to confirm the API is running.")
    def root():
        return {"message": "app api is running"}

    @app.get("/metrics", tags=["health"], summary="Prometheus metrics", description="Exposes Prometheus-formatted runtime metrics for scraping and monitoring.")
    async def metrics():
        metrics_handler = create_metrics_endpoint()
        return await metrics_handler()

    app.include_router(api_router)
    return app
