from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from slowapi.errors import RateLimitExceeded
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from app.api import api_router
from app.api.v1.endpoints.metrics import create_metrics_endpoint
from app.core.settings import settings
from app.db import engine
from app.core.exceptions import (
    AppError,
    app_error_handler,
    http_exception_handler,
    rate_limit_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
    database_exception_handler,
)
from app.core.http_metrics_middleware import HTTPMetricsMiddleware
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware
from app.core.rate_limit import limiter
from app.core.ai_controls import AIRedisStore
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
                redis_client = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
                redis_client.ping()

            if settings.kafka_enabled:
                try:
                    if KafkaProducer is None:
                        raise RuntimeError("Kafka client is not installed")
                    kafka_producer = KafkaProducer(
                        bootstrap_servers=settings.kafka_bootstrap_servers,
                        api_version_auto_timeout_ms=3000,
                        request_timeout_ms=3000,
                    )
                    if not kafka_producer.bootstrap_connected():
                        logger.warning(
                            "Kafka broker is not available during startup; continuing without Kafka producer at %s",
                            settings.kafka_bootstrap_servers,
                        )
                        kafka_producer.close(timeout=3)
                        kafka_producer = None
                except Exception as exc:
                    logger.warning(
                        "Kafka producer unavailable during startup; continuing in degraded mode. broker=%s error=%s",
                        settings.kafka_bootstrap_servers,
                        exc,
                        exc_info=True,
                    )
                    kafka_producer = None

            app.state.redis_client = redis_client
            app.state.kafka_producer = kafka_producer
            yield
        finally:
            try:
                await app.state.ai_redis_store.close()
            except Exception:
                logger.error("Failed to close AI Redis store during shutdown", exc_info=True)

            if kafka_producer is not None:
                try:
                    kafka_producer.close(timeout=3)
                except Exception:
                    logger.error("Failed to close Kafka producer during shutdown", exc_info=True)

            if redis_client is not None:
                try:
                    redis_client.close()
                except Exception:
                    logger.error("Failed to close Redis client during shutdown", exc_info=True)

            try:
                engine.dispose()
            except Exception:
                logger.error("Failed to dispose database engine during shutdown", exc_info=True)

    app = FastAPI(
        title="SmartHealth API",
        version=settings.api_version,
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
    app.state.ai_redis_store = AIRedisStore()

    app.openapi_tags = [
        # System & Authentication
        {"name": "health", "description": "Health checks and service status endpoints."},
        {"name": "auth", "description": "Authentication, login, token management, and user identity flows."},
        
        # Core Resources
        {"name": "patients", "description": "Patient profiles, demographics, and patient-specific lookups."},
        {"name": "providers", "description": "Provider profiles, provider schedules, and provider-specific data."},
        {"name": "departments", "description": "Department catalog, organization structure, and metadata."},
        
        # Scheduling & Availability
        {"name": "appointments", "description": "Appointment booking, cancellation, rescheduling, visit management, and workflows."},
        {"name": "slots", "description": "Availability slots, slot reservations, and schedule management."},
        {"name": "services", "description": "Service offerings, service catalog, publishing, and service management."},
        
        # Analytics & Operations
        {"name": "analytics", "description": "Operational analytics, utilization metrics, and performance reporting."},
        {"name": "reports", "description": "Generated reports, analytics exports, and data summaries."},
        {"name": "tasks", "description": "Background task status, job tracking, and operational jobs."},
        
        # Discovery & Search
        {"name": "search", "description": "Semantic search for services and appointment availability."},
        {"name": "public", "description": "Public catalog endpoints available without authentication."},
        
        # User Features
        {"name": "notifications", "description": "User notifications, alerts, and message delivery."},
        {"name": "assistant", "description": "AI healthcare assistant, recommendations, and utilization report generation."},
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
    app.exception_handler(SQLAlchemyError)(database_exception_handler)
    app.exception_handler(Exception)(unexpected_exception_handler)

    @app.get("/", tags=["health"], summary="Service status", description="Returns the current API service status.")
    def root():
        return {"message": "SmartHealth API is running"}

    @app.get("/metrics", tags=["health"], summary="Prometheus metrics", description="Exposes Prometheus-formatted runtime metrics for scraping and monitoring.")
    async def metrics():
        metrics_handler = create_metrics_endpoint()
        return await metrics_handler()

    app.include_router(api_router)
    return app
