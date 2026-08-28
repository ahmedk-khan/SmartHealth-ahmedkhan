import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
try:
    from kafka import KafkaProducer
except ImportError:  # pragma: no cover
    KafkaProducer = None
from pydantic import BaseModel, Field

from app.core.settings import settings
from app.db import engine
from app.repositories.health import HealthRepository

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

try:
    from temporalio import client as temporal_client
except ImportError:  # pragma: no cover
    temporal_client = None

router = APIRouter()


def _check_redis_connection() -> None:
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    client.ping()


def _check_kafka_connection() -> bool:
    if KafkaProducer is None:
        return False
    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        api_version_auto_timeout_ms=3000,
        request_timeout_ms=3000,
    )
    connected = producer.bootstrap_connected() is True
    producer.close(timeout=3)
    return connected


class HealthResponse(BaseModel):
    """Simple health check response."""

    status: str = Field(..., description="Service status: 'ok' means the application is running.")


class ReadinessCheckResult(BaseModel):
    """Result of individual dependency check (ok, disabled, or error: <reason>)."""

    pass  # Dynamic dict, documented in ReadinessResponse


class ReadinessResponse(BaseModel):
    """Readiness probe response with per-dependency health status."""

    status: str = Field(
        ...,
        description="Overall readiness status: 'ready' (HTTP 200) if all critical dependencies are ok, 'not_ready' (HTTP 503) if any are failing.",
    )
    checks: dict[str, str] = Field(
        ...,
        description="Per-dependency check results: values are 'ok', 'disabled', or 'error: Service temporarily unavailable'.",
        examples=[
            {
                "database": "ok",
                "redis": "ok",
                "kafka": "disabled",
                "temporal": "error: Service temporarily unavailable",
            }
        ],
    )


@router.get(
    "/health",
    tags=["health"],
    summary="Health check",
    description="Confirms that the application is running and ready to serve requests.",
    response_model=HealthResponse,
    responses={
        200: {
            "description": "Service is running.",
            "content": {
                "application/json": {
                    "example": {"status": "ok"},
                }
            },
        },
    },
)
def health():
    return {"status": "ok"}


@router.get(
    "/health/ready",
    tags=["health"],
    summary="Readiness check",
    description="Verifies that the API and its critical dependencies (database, Redis, Kafka, Temporal) are healthy and available. Returns 200 if ready, 503 if not ready.",
    response_model=ReadinessResponse,
    responses={
        200: {
            "description": "All critical dependencies are healthy.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ready",
                        "checks": {
                            "database": "ok",
                            "redis": "ok",
                            "kafka": "ok",
                            "temporal": "ok",
                        },
                    }
                }
            },
        },
        503: {
            "description": "One or more critical dependencies are unhealthy or unavailable.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "not_ready",
                        "checks": {
                            "database": "ok",
                            "redis": "error: Service temporarily unavailable",
                            "kafka": "error: Service temporarily unavailable",
                            "temporal": "error: Service temporarily unavailable",
                        },
                    }
                }
            },
        },
    },
)
async def ready():
    checks: dict[str, str] = {}
    has_errors = False

    try:
        await run_in_threadpool(HealthRepository(engine).check_database_connection)
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - runtime dependency check
        logger.exception("Database readiness check failed", extra={"dependency": "database"})
        checks["database"] = "error: Service temporarily unavailable"
        has_errors = True

    if redis is not None:
        try:
            await run_in_threadpool(_check_redis_connection)
            checks["redis"] = "ok"
        except Exception as exc:  # pragma: no cover - runtime dependency check
            logger.exception("Redis readiness check failed", extra={"dependency": "redis"})
            checks["redis"] = "error: Service temporarily unavailable"
            has_errors = True
    else:
        checks["redis"] = "disabled"

    if settings.kafka_enabled:
        try:
            connected = await run_in_threadpool(_check_kafka_connection)
            if connected:
                checks["kafka"] = "ok"
            else:
                logger.error("Kafka readiness check failed: bootstrap not connected", extra={"dependency": "kafka"})
                checks["kafka"] = "error: Service temporarily unavailable"
                has_errors = True
        except Exception as exc:  # pragma: no cover - runtime dependency check
            logger.exception("Kafka readiness check failed", extra={"dependency": "kafka"})
            checks["kafka"] = "error: Service temporarily unavailable"
            has_errors = True
    else:
        checks["kafka"] = "disabled"

    if temporal_client is not None:
        try:
            client = await asyncio.wait_for(
                temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace),
                timeout=5,
            )
            client.get_workflow_handle("health-check-readiness")
            checks["temporal"] = "ok"
        except Exception as exc:  # pragma: no cover - runtime dependency check
            logger.exception("Temporal readiness check failed", extra={"dependency": "temporal"})
            checks["temporal"] = "error: Service temporarily unavailable"
            has_errors = True
    else:
        checks["temporal"] = "disabled"

    status = "ready" if not has_errors else "not_ready"
    code = 200 if not has_errors else 503
    return JSONResponse(status_code=code, content={"status": status, "checks": checks})

