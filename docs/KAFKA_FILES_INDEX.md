# Kafka Implementation - File Location Index

## Core Kafka Components

### 1. Producer Implementation
**File:** `app/integrations/kafka_client.py`
- **Class:** `KafkaEventPublisher`
- **Key Methods:**
  - `publish_event()` - Synchronous event publishing
  - `publish_event_async()` - Async event publishing
  - `_validate_metadata()` - PHI redaction with allowlist
  - `_build_topic_name()` - Topic naming convention

### 2. Event Service (High-level API)
**File:** `app/services/healthcare_event_service.py`
- **Class:** `HealthcareEventService`
- **Key Methods:**
  - `publish_appointment_event()` - Appointment events
  - `publish_service_event()` - Service events
  - `publish_billing_event()` - Billing events
  - `publish_resource_event()` - Generic event publishing
- **Special:** Auto-captures `correlation_id` and `request_id` from context

### 3. Consumer Implementation
**File:** `app/workers/analytics_consumer.py`
- **Class:** `AnalyticsConsumer`
- **Key Methods:**
  - `consumer` (property) - Creates KafkaConsumer with proper config
  - `_topics()` - Lists subscribed topics
  - `process_message()` - Validates and processes received events
  - `_is_safe_payload()` - PHI validation (deny-list check)
  - `_update_appointment_metrics()` - Analytics processing
  - `_update_service_metrics()` - Analytics processing
  - `run()` - Main consumer loop (manual offset commits)
- **Entry Point:** `python -m app.workers.analytics_consumer`

---

## Configuration & Settings

### Kafka Settings
**File:** `app/core/settings.py` (Lines 32-35)
```python
kafka_enabled: bool = Field(default=False, alias="KAFKA_ENABLED")
kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
kafka_consumer_group: str = Field(default="app-analytics", alias="KAFKA_CONSUMER_GROUP")
kafka_topic_prefix: str = Field(default="app", alias="KAFKA_TOPIC_PREFIX")
```

### Docker Compose Setup
**File:** `docker-compose.yml` (Lines 212-258)
- Kafka broker (Confluent image: `confluentinc/cp-kafka:7.5.0`)
- Zookeeper coordination
- Internal/External listeners
- Auto-topic creation enabled

---

## Data Models

### Outbox Pattern (Fallback Storage)
**File:** `app/models/outbox.py`
- **Table:** `outbox_events`
- **Purpose:** Store events when Kafka is unavailable
- **Columns:** event_id, event_type, entity_type, entity_id, payload, status, attempts, last_error

### Idempotency Tracking
**File:** `app/models/processed_event.py`
- **Table:** `processed_events`
- **Purpose:** Prevent duplicate processing (unique constraint on event_id + consumer)
- **Columns:** event_id, consumer, processed_at

### Analytics Models
**File:** `app/models/analytics.py`
- Stores aggregated metrics from consumed events
- Indexed by topic for fast queries

---

## Event Publishing Points (Where Events Enter Kafka)

### 1. Appointment Events
**File:** `app/services/appointment_service.py`
- Line ~101: `publish_appointment_event("appointment.created", ...)`
- Line ~232: `publish_appointment_event("appointment.visit_status_changed", ...)`

**Topics Generated:**
- `app.appointment.created`
- `app.appointment.cancelled` (in cancel method)
- `app.appointment.rescheduled`
- `app.appointment.visit_status_changed`

### 2. Service Events
**File:** `app/services/service_management.py`
- Line ~57: `publish_service_event("service.created", ...)`
- Line ~125: `publish_service_event("service.unpublished", ...)`

**Topics Generated:**
- `app.service.created`
- `app.service.unpublished`
- `app.service.published` (from Temporal activity)

### 3. Temporal Activities
**File:** `app/temporal/activities.py`
- `publish_service_published_event()` - Activity
- `publish_appointment_created_event()` - Activity

---

## Workers & Background Processes

### Analytics Consumer Worker
**File:** `app/workers/analytics_consumer.py`
- **Runs:** `python -m app.workers.analytics_consumer`
- **Consumer Group:** `app-analytics`
- **Subscriptions:** app.appointment.*, app.service.*
- **Processing:** Updates analytics_daily metrics, deduplicates via processed_events

### Service Publish Worker
**File:** `app/workers/service_publish_worker.py`
- Temporal worker that runs service publishing workflows
- Executes `publish_service_published_event` activity

---

## Testing & Validation

### Integration Tests
**File:** `tests/integration/test_docker_infrastructure.py`
- Test: `test_kafka_publish_and_consume_round_trip()` (Lines 41+)
- Tests actual pub/sub flow end-to-end
- Verifies message round-trip with actual Kafka broker

### Kafka Failure Tests
**File:** `tests/integration/test_kafka_failure.py`
- Test: `test_kafka_broker_failure_is_converted_to_outbox()`
- Verifies outbox fallback when broker is down

### Event Safety Tests
**File:** `tests/unit/test_event_safety.py`
- Test: `test_kafka_metadata_redacts_nested_phi_keys()`
- Validates PHI redaction with allowlist

---

## Health Checks & Monitoring

### Health Endpoint
**File:** `app/api/v1/endpoints/health.py`
- Function: `_check_kafka_connection()` (Lines 37-48)
- Attempts producer creation to verify broker connectivity
- Returns: `kafka_status` in health response

### App Factory Integration
**File:** `app/core/app_factory.py`
- Initializes Kafka producer on app startup if enabled
- Passes to dependency injection container

---

## Documentation

### Event Contracts
**File:** `docs/events.md`
- Canonical event model and envelope format
- Full event catalog with producers, triggers, payloads
- Event types:
  - `appointment.created`
  - `appointment.cancelled`
  - `appointment.rescheduled`
  - `appointment.visit_status_changed`
  - `service.published`
  - (and more)

### Architecture Diagrams
**File:** `docs/diagrams/architecture.md`
- Shows API → Kafka → Analytics Consumer flow

### Runbook
**File:** `docs/runbook.md`
- Operational guide including Kafka startup/debugging
- Kafka topics listing and consumer monitoring commands

### Design Document
**File:** `docs/design.md`
- Explains outbox pattern and event publishing guarantees

---

## Topic Catalog

| Topic | Producer | Trigger | Consumer |
|-------|----------|---------|----------|
| `app.appointment.created` | AppointmentService | Appointment booked | AnalyticsConsumer |
| `app.appointment.cancelled` | AppointmentService | Appointment cancelled | AnalyticsConsumer |
| `app.appointment.rescheduled` | AppointmentService | Appointment rescheduled | AnalyticsConsumer |
| `app.appointment.visit_status_changed` | AppointmentService | Visit status changes | AnalyticsConsumer |
| `app.service.created` | ServiceManagement | New service created | AnalyticsConsumer |
| `app.service.unpublished` | ServiceManagement | Service unpublished | AnalyticsConsumer |
| `app.service.published` | Temporal Activity | Service published | AnalyticsConsumer |

---

## Event Flow Summary

```
User Action
    ↓
API Endpoint (e.g., POST /appointments)
    ↓
Service Layer (e.g., AppointmentService.create())
    ↓
Business Logic (saga, database commit)
    ↓
HealthcareEventService.publish_appointment_event()
    ↓
KafkaEventPublisher.publish_event()
    ├→ Validates no PHI
    ├→ Builds topic: app.appointment.created
    ├→ Sends to broker
    └→ On failure: stores in outbox_events table
    ↓
Kafka Topic: app.appointment.created (with offset)
    ↓
AnalyticsConsumer (subscribed, consumer group: app-analytics)
    ↓
Idempotency Check (processed_events table)
    ↓
Process Message (update analytics_daily)
    ↓
Commit Offset → ready for next message
```

---

## How to Find Code by Kafka Concept

| Looking for... | Check these files |
|---|---|
| Producer code | `app/integrations/kafka_client.py` |
| Where events are published | `app/services/appointment_service.py`, `app/services/service_management.py` |
| Consumer logic | `app/workers/analytics_consumer.py` |
| Topic definitions | `app/workers/analytics_consumer.py#_topics()` |
| Offset management | `app/workers/analytics_consumer.py#consumer` property |
| Broker config | `docker-compose.yml` |
| Settings/credentials | `app/core/settings.py` |
| Idempotency handling | `app/models/processed_event.py` + `app/workers/analytics_consumer.py#process_message()` |
| Outbox fallback | `app/models/outbox.py` + `app/services/healthcare_event_service.py#_save_outbox()` |
| PHI validation | `app/integrations/kafka_client.py#_validate_metadata()` |
| Health checks | `app/api/v1/endpoints/health.py` |
| End-to-end flow | `docs/events.md` + `docs/design.md` |

---

## Quick Commands for Supervisor Demo

### Check if Kafka is Running
```bash
curl http://localhost:8000/api/v1/health
# Look for "kafka": "connected"
```

### List All Topics
```bash
docker exec kafka kafka-topics --bootstrap-server kafka:29092 --list
```

### Monitor Consumer
```bash
docker exec kafka kafka-consumer-groups \
  --bootstrap-server kafka:29092 \
  --group app-analytics \
  --describe
```

### View Published Events
```bash
docker exec kafka kafka-console-consumer \
  --bootstrap-server kafka:29092 \
  --topic app.appointment.created \
  --from-beginning \
  --max-messages 10
```

### Check Database Analytics
```bash
# Connect to PostgreSQL
SELECT COUNT(*), topic FROM analytics_processed_events GROUP BY topic;
```

---

## Correlation Across System

Every event includes IDs for tracing:
- **event_id:** Unique Kafka message ID
- **correlation_id:** Groups related events across workflows
- **request_id:** HTTP request that triggered the event
- **entity_id:** The business entity (appointment ID, service ID, etc.)

**Example Trace:**
1. User makes API request with header `X-Correlation-ID: abc123`
2. AppointmentService publishes event with `correlation_id: abc123`
3. Event appears in Kafka with same `correlation_id`
4. AnalyticsConsumer reads event, stores in DB with `correlation_id`
5. Operator can trace entire flow: API → Kafka → Analytics using `abc123`

---

## Fallback & Resilience Patterns

### Outbox Pattern (Broker Down)
```
Publish Event
    ↓
Try Kafka
    ├→ Success: Return published status
    └→ Failure: Store in outbox_events table
            ↓
        Scheduled job retries outbox
            ↓
        Once broker recovers, events published
```

### Idempotent Consumer
```
Receive Event (offset N)
    ↓
Check: Is event_id + consumer_group in processed_events?
    ├→ Yes: Skip (already processed)
    └→ No: Process, then insert into processed_events
    ↓
Commit offset N → move forward
```

### Producer Retry
```
Send Event
    ↓
Broker ACK?
    ├→ Yes: Success
    └→ No: Retry (3x with 250ms backoff)
            ↓
            Still fails? Raise exception, trigger outbox storage
```

