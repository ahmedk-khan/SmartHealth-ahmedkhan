# Workflows & Background Processing Guide

This document maps all asynchronous workflows, background tasks, and distributed processing components within the SmartHealth application.

---

## 1. Directory Structure Map

```
app/
├── celery_app.py                      # Celery application initialization & schedules
├── temporal/
│   └── worker.py                      # Temporal worker process (registers & runs workflows/activities)
├── workflows/
│   ├── appointment_saga_workflow.py   # Deterministic appointment booking saga workflow
│   ├── appointment_saga_activities.py # Non-deterministic database/external booking activities
│   ├── service_publish_workflow.py    # Deterministic service publication workflow
│   ├── service_publish_activities.py  # Non-deterministic embedding/chunking activities
│   ├── temporal_logging.py            # Tracing/correlation context propagation helper
│   └── temporal_policies.py           # Workflows and activities retry configurations
└── workers/
    ├── analytics_consumer.py          # Kafka event consumer for analytics aggregation
    └── tasks/                         # Celery tasks
        ├── analytics_tasks.py         # Celery tasks for metrics compilation
        ├── appointment_tasks.py       # Celery tasks for reminder dispatches
        └── outbox_tasks.py            # Celery tasks for Transactional Outbox publishing
```

---

## 2. Temporal Workflows (Orchestrated & Durable)

We use Temporal to orchestrate complex, multi-step business transactions requiring durability and fault tolerance.

### A. Appointment Booking Saga Workflow
- **Workflow Class**: `AppointmentSagaWorkflow` in [`app/workflows/appointment_saga_workflow.py`](file:///d:/Emumba/SmartHealth/SmartHealth-ahmedkhan/app/workflows/appointment_saga_workflow.py)
- **Activities**: [`app/workflows/appointment_saga_activities.py`](file:///d:/Emumba/SmartHealth/SmartHealth-ahmedkhan/app/workflows/appointment_saga_activities.py)
- **Description**: Orchestrates the appointment booking saga. Enforces slot reservation, pending record creation, billing prechecks, and dispatches reminders/confirmations.
- **Compensations**: If billing or scheduling fails, the workflow executes compensation activities (`release_slot`, `cancel_reminder`, `cancel_pending_appointment`) to roll back state.

### B. Service Publication Workflow
- **Workflow Class**: `ServicePublishWorkflow` in [`app/workflows/service_publish_workflow.py`](file:///d:/Emumba/SmartHealth/SmartHealth-ahmedkhan/app/workflows/service_publish_workflow.py)
- **Activities**: [`app/workflows/service_publish_activities.py`](file:///d:/Emumba/SmartHealth/SmartHealth-ahmedkhan/app/workflows/service_publish_activities.py)
- **Description**: Handles structured medical service publishing. Performs schema validation, splits description catalogs into semantic text chunks, embeds the chunks using ML models (Fake or HuggingFace), and saves chunks for semantic search.

### C. Worker Process
- **File**: [`app/temporal/worker.py`](file:///d:/Emumba/SmartHealth/SmartHealth-ahmedkhan/app/temporal/worker.py)
- **Execution Command**: `python -m app.temporal.worker`
- **Description**: Connects to the Temporal server and runs a listening loop to process workflow/activity tasks assigned to the task queue.

---

## 3. Celery Tasks (Time-Triggered & Background)

Celery manages background tasks and periodically scheduled events (cron-like actions).

- **App Initialization**: [`app/celery_app.py`](file:///d:/Emumba/SmartHealth/SmartHealth-ahmedkhan/app/celery_app.py)
- **Execution Command**: `celery -A app.celery_app worker --loglevel=info`

### Enqueued Tasks:
1. **Appointment Reminders** (`enqueue_due_appointment_reminders`): Runs periodically (every 15 mins) via Celery Beat, querying the database for upcoming appointments due for reminder dispatches.
2. **Transactional Outbox Event Publisher** (`publish_pending_events`): Polling publisher that regularly picks up outstanding database events (saved in the outbox table) and publishes them to Kafka to ensure transactional messaging safety.
3. **Analytics Metrics Compilation** (`compile_daily_analytics`): Aggregates system metrics periodically.

---

## 4. Kafka Integration (Event-Driven Analytics)

- **Analytics Consumer**: [`app/workers/analytics_consumer.py`](file:///d:/Emumba/SmartHealth/SmartHealth-ahmedkhan/app/workers/analytics_consumer.py)
- **Description**: A long-running background worker process that subscribes to Kafka message topics (e.g. `appointment.created`, `service.published`). It aggregates and updates analytics metrics in the database asynchronously, decoupleing query overhead from live APIs.

---

## 5. Redis Integration (Cache, Broker & Rate Limiting)

Redis serves two distinct roles in the application:

1. **Celery Broker & Backend**:
   - Celery uses Redis as a message broker to queue tasks (`broker=settings.celery_broker_url`) and as a backend database to store task execution results (`backend=settings.celery_result_backend`).
2. **FastAPI Rate Limiting**:
   - SlowAPI (`app/core/rate_limit.py`) connects to Redis to track and throttle excessive API hits (such as brute-force registration or login requests).
