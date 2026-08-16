# Operations Runbook

## Purpose

This runbook provides standard operational procedures for the SmartHealth platform, including startup, health validation, troubleshooting, and recovery for common production issues.

It is intended for engineering and site-reliability use and should be kept current with the live system environment.

## System Overview

SmartHealth is a FastAPI-based healthcare platform with:

- PostgreSQL persistence
- Redis-backed idempotency and cache access
- Celery background workers
- Kafka event streaming
- Temporal workflow orchestration
- Prometheus metrics exposure
- structured JSON logging with correlation IDs

## Service Topology

The principal runtime services are:

- API service: provides the HTTP API and Swagger docs
- Celery worker: processes asynchronous tasks
- analytics consumer: consumes stream events for analytics processing
- PostgreSQL: application database
- Redis: idempotency and task cache state
- Kafka: event publishing and consumer integration
- Temporal: service publish workflow orchestration

## Startup and Shutdown

### Local startup

```bash
docker compose up -d
```

### Application startup

```bash
uvicorn app.main:app --reload
```

### Celery worker startup

```bash
celery -A app.celery_app worker --loglevel=info
```

### Analytics consumer

```bash
python -m app.workers.analytics_consumer
```

### Shutdown

```bash
docker compose down
```

Use the volume removal variant only when a clean reset is required:

```bash
docker compose down -v
```

---

## Health Checks

### API health

```bash
curl http://localhost:8000/health
```

Expected result:

```json
{"status": "ok"}
```

### Metrics endpoint

```bash
curl http://localhost:8000/metrics
```

This should return Prometheus-formatted metrics and is the primary endpoint for scraping.

### Swagger UI

Open:

```text
http://localhost:8000/docs
```

This is useful for verifying route registration and contract integrity.

### Service dependencies

Verify:

- PostgreSQL on port 5432
- Redis on port 6379
- Kafka on port 9092 / 29092
- Temporal on port 7233

---

## Log and Trace Review

### Correlation ID usage

All request and workflow flows should carry a correlation ID. Validate logs using the same request ID or correlation ID across application and worker components.

### JSON log expectations

Logs should be structured JSON and must not contain PHI or personal user content. Use the correlation ID and request ID fields to trace activity across the system.

### Examples

Look for fields such as:

- timestamp
- level
- logger
- message
- operation
- correlation_id
- request_id
- user_id
- appointment_id

---

## Common Incident Response

### 1. API is not responding

Check:

1. Docker containers state
2. process logs for the API service
3. environment variables and database reachability
4. database connectivity and migration state

Commands:

```bash
docker compose ps
docker compose logs api --tail 200
```

### 2. Database connection errors

Verify:

- Postgres container is running
- .env values match the expected database settings
- migrations are applied

Command:

```bash
alembic upgrade head
```

### 3. Celery worker stuck or not processing jobs

Check:

```bash
docker compose logs celery-worker --tail 200
```

Also verify:

- Redis is available
- PostgreSQL is reachable
- broker settings are valid
- worker startup command is correct

### 4. Temporal workflow errors

Check:

- Temporal container health
- workflow execution logs and workflow status
- service publish workflow activity failures

Useful endpoint:

```text
http://localhost:7233
```

### 5. Metrics endpoint empty or not scraping

Check:

- app is running and /metrics is enabled
- Prometheus target config is correct
- HTTP middleware is not skipping required endpoints unintentionally
- the service is exposing counters and histograms without registration errors

---

## Recovery Procedures

### Graceful restart

```bash
docker compose restart api celery-worker analytics-consumer
```

### Clean reset

Use this only for environment reset and local development recovery:

```bash
docker compose down -v
```

Then restart:

```bash
docker compose up -d --build
```

### Database recovery

If the schema is inconsistent:

```bash
alembic current
alembic upgrade head
```

If a manual reset is required and the environment is non-production, drop and recreate the schema carefully and reseed data.

---

## Monitoring and Alerting Checklist

The following should be monitored in normal operation:

- API latency and error rates
- task queue backlogs
- worker crashes or restarts
- database connection issues
- Kafka consumer lag or delivery failures
- workflow failures in Temporal
- Prometheus scrape success for /metrics

## Escalation Guide

Escalate to the engineering owner when:

- API is unavailable for a sustained period
- repeated workflow failures block core business operations
- data integrity issues appear in appointments, billing, or slot availability
- metrics are missing or stale for production monitoring
- event consumers fail to process the critical event stream

## Documentation Maintenance

This runbook should be reviewed when:

- services are added or removed
- deployment topology changes
- observability pipelines change
- event contracts or background job flows change
- monitoring or alert rules change

## Related Documentation

- [design.md](design.md)
- [events.md](events.md)
- [STRUCTURED_LOGGING.md](STRUCTURED_LOGGING.md)
