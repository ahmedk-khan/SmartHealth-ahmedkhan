import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from kafka import KafkaProducer
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.settings import settings
from app.db import engine

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

try:
    from temporalio import client as temporal_client
except ImportError:  # pragma: no cover
    temporal_client = None

router = APIRouter()


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
        description="Per-dependency check results: values are 'ok', 'disabled', or 'error: <exception_type>'.",
        examples={
            "database": "ok",
            "redis": "ok",
            "kafka": "disabled",
            "temporal": "error: RuntimeError",
        },
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
                            "redis": "error: ConnectionError",
                            "kafka": "error: NoBrokersAvailable",
                            "temporal": "error: RuntimeError",
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
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - runtime dependency check
        checks["database"] = f"error: {type(exc).__name__}"
        has_errors = True

    if redis is not None:
        try:
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # pragma: no cover - runtime dependency check
            checks["redis"] = f"error: {type(exc).__name__}"
            has_errors = True
    else:
        checks["redis"] = "disabled"

    if settings.kafka_enabled:
        try:
            producer = KafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                api_version_auto_timeout_ms=3000,
                request_timeout_ms=3000,
            )
            connected = producer.bootstrap_connected() is True
            producer.close(timeout=3)
            checks["kafka"] = "ok" if connected else "error: kafka bootstrap not connected"
            if not connected:
                has_errors = True
        except Exception as exc:  # pragma: no cover - runtime dependency check
            checks["kafka"] = f"error: {type(exc).__name__}"
            has_errors = True
    else:
        checks["kafka"] = "disabled"

    if temporal_client is not None:
        try:
            client = await asyncio.wait_for(
                temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace),
                timeout=5,
            )
            await asyncio.wait_for(client.get_workflow_handle("health-check-readiness"), timeout=1)
            checks["temporal"] = "ok"
        except Exception as exc:  # pragma: no cover - runtime dependency check
            checks["temporal"] = f"error: {type(exc).__name__}"
            has_errors = True
    else:
        checks["temporal"] = "disabled"

    status = "ready" if not has_errors else "not_ready"
    code = 200 if not has_errors else 503
    return JSONResponse(status_code=code, content={"status": status, "checks": checks})
