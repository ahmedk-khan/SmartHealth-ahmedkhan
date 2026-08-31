# SmartHealth Kafka Flow - Quick Visual Reference

## 1. PRODUCER SIDE: How Events Get Published

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER CREATES APPOINTMENT                        │
│              POST /api/v1/appointments with slot_id=55                  │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             app/api/v1/endpoints/appointments.py                        │
│                  API Route Handler (@router.post)                       │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│               app/services/appointment_service.py                       │
│                    AppointmentService.create()                          │
│  1. Validate patient & slot availability                               │
│  2. Run Temporal saga workflow                                         │
│  3. Create appointment in database                                     │
│  4. ✅ Transaction committed                                            │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│           app/services/healthcare_event_service.py                      │
│        HealthcareEventService.publish_appointment_event()               │
│                                                                         │
│  Build event payload:                                                   │
│  {                                                                      │
│    "event_id": "uuid-123",                                              │
│    "event_type": "appointment.created",                                 │
│    "occurred_at": "2026-08-21T10:30:00Z",                               │
│    "entity_type": "appointment",                                        │
│    "entity_id": "101",                                                  │
│    "correlation_id": "from-http-header",                                │
│    "request_id": "http-request-id",                                     │
│    "source": "smarthealth-api",                                         │
│    "data": {                                                            │
│      "appointment_id": 101,                                             │
│      "patient_id": 23,                                                  │
│      "provider_id": 7,                                                  │
│      "service_id": 14,                                                  │
│      "slot_id": 55,                                                     │
│      "status": "CONFIRMED"                                              │
│    }                                                                    │
│  }                                                                      │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             app/integrations/kafka_client.py                            │
│              KafkaEventPublisher.publish_event()                        │
│                                                                         │
│  VALIDATION:                                                            │
│  ✅ Check no PHI (patient_name, email, phone, diagnosis, etc.)         │
│  ✅ Only allow whitelisted fields                                       │
│  ✅ Redact nested structures                                            │
│                                                                         │
│  CONSTRUCTION:                                                          │
│  Topic = "app" + "." + "appointment.created"                            │
│       → "app.appointment.created"                                       │
│  Key   = entity_id (for partitioning)                                   │
│  Value = JSON event payload                                             │
│                                                                         │
│  PRODUCER CONFIG:                                                       │
│  acks="all"           → Wait for all broker replicas                    │
│  retries=3            → Retry up to 3 times on failure                  │
│  retry_backoff_ms=250 → Exponential backoff                             │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ├─────────────────────┬──────────────────────────┐
                      │                     │                          │
                      ▼                     ▼                          ▼
           ✅ SUCCESS           ⚠️ RETRY FAILS           ❌ KAFKA DOWN
           Published to          Exponential backoff        Store in outbox
           Kafka Broker          3 attempts                 outbox_events table
           Returns:              (Exception raised)         Scheduled job will
           {                                                 retry later
            "status": "published",
            "topic": "app.appointment.created",
            "partition": 0,
            "offset": 12345,
            "event_id": "uuid-123"
           }

```

---

## 2. KAFKA BROKER: Topic & Message Storage

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         KAFKA CLUSTER                                    │
│                    (docker-compose.yml)                                  │
│                                                                          │
│  Broker ID: 1                                                            │
│  Image: confluentinc/cp-kafka:7.5.0                                      │
│  Listeners:                                                              │
│    Internal: kafka:29092   (for services)                                │
│    External: localhost:9092 (for dev clients)                            │
│                                                                          │
│  Auto-create topics: enabled                                             │
│  Replication factor: 1 (dev), 3 (prod)                                   │
└──────────────────────────────────────────────────────────────────────────┘

Topic: app.appointment.created
├── Partition 0 (broker-1, current dev setup)
│   ├── Offset 0: {"event_id": "uuid-1", ...}
│   ├── Offset 1: {"event_id": "uuid-2", ...}
│   ├── Offset 2: {"event_id": "uuid-3", ...}  ← Consumer is here
│   ├── Offset 3: {"event_id": "uuid-4", ...}  ← New message
│   └── ...
│
├── Partition 1 (broker-2 in cluster)  [only in production with 3+ brokers]
│   └── ...
│
└── Partition 2 (broker-3 in cluster)  [only in production with 3+ brokers]
    └── ...

CONSUMER GROUP: app-analytics
├── Consumer 1 → reads Partition 0 (at offset 3)
├── Consumer 2 → reads Partition 1 (if exists)
└── Consumer 3 → reads Partition 2 (if exists)
```

---

## 3. CONSUMER SIDE: How Analytics Processes Events

```
┌─────────────────────────────────────────────────────────────────────────┐
│          app/workers/analytics_consumer.py                              │
│             AnalyticsConsumer.run()                                     │
│          (Runs as: python -m app.workers.analytics_consumer)            │
│                                                                         │
│  Startup:                                                               │
│  - Create KafkaConsumer (auto_offset_reset="earliest")                  │
│  - Join consumer group: "app-analytics"                                 │
│  - Subscribe to topics:                                                 │
│    * app.appointment.created                                            │
│    * app.appointment.cancelled                                          │
│    * app.appointment.rescheduled                                        │
│    * app.appointment.visit_status_changed                               │
│    * app.service.published                                              │
│  - enable_auto_commit=False (manual control)                            │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   MESSAGE LOOP                                          │
│         for message in self.consumer:                                   │
│                                                                         │
│  Step 1: Receive Message                                                │
│  ─────────────────────────────────────────────────────────────────────  │
│  {                                                                      │
│    "topic": "app.appointment.created",                                  │
│    "partition": 0,                                                      │
│    "offset": 12345,                                                     │
│    "value": {                                                           │
│      "event_id": "uuid-123",                                            │
│      "event_type": "appointment.created",                               │
│      "entity_id": "101",                                                │
│      ...                                                                │
│    }                                                                    │
│  }                                                                      │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 2: Validation                                                     │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  ✅ Is it JSON dict?                                                    │
│     if not isinstance(message, dict):                                   │
│       raise ConsumerConfigError()                                       │
│                                                                         │
│  ✅ Contains forbidden PHI?                                             │
│     forbidden = {"name", "email", "phone", "diagnosis", ...}            │
│     if contains_forbidden_keys(message):                                │
│       raise ConsumerConfigError()                                       │
│                                                                         │
│  ✅ Has event_id?                                                       │
│     if not message.get("event_id"):                                     │
│       raise ConsumerConfigError()                                       │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 3: Idempotency Check                                              │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  Check database: has this (event_id, consumer) been processed?          │
│                                                                         │
│  Query: SELECT * FROM processed_events                                  │
│         WHERE event_id = 'uuid-123'                                     │
│         AND consumer = 'app-analytics'                                  │
│                                                                         │
│  If exists:                                                             │
│    ❌ Duplicate! Skip processing, commit offset anyway                  │
│  If NOT exists:                                                         │
│    ✅ New event, proceed to processing                                  │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 4: Process Message                                                │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  Detect event type:                                                     │
│  if "appointment" in topic:                                             │
│    → call update_appointment_metrics()                                  │
│  elif "service" in topic:                                               │
│    → call update_service_metrics()                                      │
│                                                                         │
│  Example: update_appointment_metrics() does:                            │
│  ┌──────────────────────────────────────────────────────────┐          │
│  │ INSERT/UPDATE analytics_daily:                           │          │
│  │ {                                                        │          │
│  │   date: 2026-08-21,                                      │          │
│  │   event_type: 'appointment.created',                     │          │
│  │   count: +1,                                             │          │
│  │   metric_data: {...}                                     │          │
│  │ }                                                        │          │
│  └──────────────────────────────────────────────────────────┘          │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 5: Track Processed Event (Idempotency Record)                    │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  INSERT INTO processed_events                                           │
│  {                                                                      │
│    event_id: 'uuid-123',                                                │
│    consumer: 'app-analytics',                                           │
│    processed_at: NOW()                                                  │
│  }                                                                      │
│                                                                         │
│  Unique constraint prevents duplicate inserts:                          │
│  UNIQUE(event_id, consumer)                                             │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 6: Commit & Advance                                               │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  Only commit after successful processing:                               │
│  self.consumer.commit()                                                 │
│                                                                         │
│  Effect:                                                                │
│  - Update consumer's offset bookmark → 12345                            │
│  - Next message read will be from offset 12346                          │
│  - If consumer crashes, restart from 12345 (no loss, slight dupes)      │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼ Loop back to Step 1
                    (Wait for next message from broker)
```

---

## 4. DATABASE: Analytics & Idempotency

```
PostgreSQL Database
│
├── outbox_events (Fallback for broker down)
│   ├── event_id (PK, unique)
│   ├── event_type
│   ├── payload (JSON)
│   ├── status: [PENDING, PUBLISHED, FAILED]
│   ├── attempts
│   ├── last_error
│   └── created_at
│
├── processed_events (Idempotency - prevents dupes)
│   ├── event_id (unique key part 1)
│   ├── consumer (unique key part 2) → "app-analytics"
│   └── processed_at
│   
│   Unique constraint: (event_id, consumer)
│   → Same event cannot be processed twice by same consumer
│   → Different consumers can process same event
│
├── analytics_daily (Aggregated metrics)
│   ├── date
│   ├── event_type
│   ├── count (incremented by consumer)
│   ├── metric_data (JSON)
│   └── topic (indexed for fast queries)
│
└── analytics_processed_events (Audit trail)
    ├── event_id
    ├── event_type
    ├── topic
    ├── payload (JSON)
    └── processed_at
```

---

## 5. END-TO-END FLOW: Single Event Journey

```
TIME    SOURCE                          ACTION                    DESTINATION
────    ──────────────────────────────  ───────────────────────   ────────────────
T=0s    User/Client                    POST /appointments         API Server

T=0.1s  API Route Handler              Validate request          AppointmentService

T=0.5s  AppointmentService             Create appointment        PostgreSQL

T=1.0s  AppointmentService             Commit transaction        PostgreSQL ✅

T=1.1s  AppointmentService             Publish event             HealthcareEventService

T=1.2s  HealthcareEventService         Build event payload       KafkaEventPublisher

T=1.3s  KafkaEventPublisher            Validate (no PHI)         Event
                                       Build topic name           Metadata

T=1.4s  KafkaEventPublisher            Send to broker            Kafka Broker

T=1.5s  Kafka Broker                   Store in partition 0      Offset: 12345

T=1.6s  Kafka Broker                   ACK to producer           KafkaEventPublisher

T=1.7s  AppointmentService             Return response           Client ✅

        ┌─ Consumer Polling ─────────────────────────────────────┐
T=2.0s  │ AnalyticsConsumer            Poll broker               Kafka Broker
T=2.1s  │ AnalyticsConsumer            Receive message           Message Payload
T=2.2s  │ AnalyticsConsumer            Validate payload          Safety Checks ✅
T=2.3s  │ AnalyticsConsumer            Check dedup               processed_events
T=2.4s  │ AnalyticsConsumer            Not found (new)           Continue ✅
T=2.5s  │ AnalyticsConsumer            Update analytics          analytics_daily
T=2.6s  │ AnalyticsConsumer            Insert dedup record       processed_events
T=2.7s  │ AnalyticsConsumer            Commit offset             Kafka Broker
        │ AnalyticsConsumer            → Ready for next msg      Offset: 12345
        └────────────────────────────────────────────────────────┘

CLIENT RECEIVES: {"appointment_id": 101, "status": "CONFIRMED"}
ANALYTICS SEES: {"date": "2026-08-21", "event_type": "appointment.created", "count": 1}
KAFKA STORES:   {"event_id": "uuid-123", "offset": 12345, "partition": 0}
```

---

## 6. FAILURE SCENARIOS

### Scenario A: Kafka Broker Down

```
AppointmentService.create()
    ↓
Publish event → KafkaEventPublisher.publish_event()
    ↓
Try to send to broker
    ↓
❌ Connection failed (broker down)
    ├─ Retry 1 (250ms backoff) → Still down
    ├─ Retry 2 (500ms backoff) → Still down
    ├─ Retry 3 (1000ms backoff) → Still down
    └─ Exception raised
    ↓
Catch in HealthcareEventService._save_outbox()
    ↓
INSERT INTO outbox_events
{
  event_id: 'uuid-123',
  status: 'PENDING',
  payload: {...},
  last_error: 'Connection failed',
  attempts: 0
}
    ↓
Return response to user (appointment still created ✅)
    ↓
Later (when broker recovers):
  Scheduled job → reads outbox_events with status=PENDING
  Retry publish → success!
  Update status → 'PUBLISHED'
```

### Scenario B: Duplicate Event in Consumer

```
Kafka Message (offset 100)
    ↓
AnalyticsConsumer receives it
    ↓
Validate ✅, Update analytics ✅
    ↓
Try to commit offset
    ↓
❌ Network issue before commit completes
    ↓
Consumer process crashes/restarts
    ↓
Consumer rejoins group, reset to offset 100
    ↓
Kafka resends same message
    ↓
AnalyticsConsumer receives it again
    ↓
Validate ✅
    ↓
Check idempotency:
  SELECT * FROM processed_events
  WHERE event_id = 'uuid-123'
  AND consumer = 'app-analytics'
    ↓
✅ Found! (already processed)
    ↓
Skip analytics update
    ↓
Commit offset anyway
    ↓
Result: Event processed only once ✅
```

### Scenario C: Consumer Lag (High Volume)

```
Messages published to Kafka:
Offset 1, 2, 3, 4, 5, 6, 7, 8, 9, 10

Consumer processing rate: 1 message/second
    ↓
Consumer position:
T=0s: At offset 0, received msg 1, committed at 1
T=1s: Received msg 2, committed at 2
T=2s: Received msg 3, committed at 3
...
T=10s: Received msg 10, committed at 10
    ↓
Consumer is caught up ✅

Broker buffer: Kept messages 1-10 (by retention policy)
Database: analytics_daily has all events aggregated

If more consumers added (horizontal scaling):
  Consumer 2 joins
  → Broker rebalances partitions
  → Consumer 1 takes partitions [0, 2, 4]
  → Consumer 2 takes partitions [1, 3, 5]
  → Both process in parallel ✅
```

---

## 7. SETTINGS & ENVIRONMENT

```
.env file or docker-compose.yml environment:

KAFKA_ENABLED=true
├── Default: false
└── Set to true to enable Kafka publishing/consuming

KAFKA_BOOTSTRAP_SERVERS=kafka:29092
├── Default: localhost:9092
├── Internal (service-to-service): kafka:29092
└── External (local dev): localhost:9092

KAFKA_CONSUMER_GROUP=app-analytics
├── Default: app-analytics
├── Used as unique identifier for consumer group
└── Offset tracking is per consumer group

KAFKA_TOPIC_PREFIX=app
├── Default: app
└── Final topic = app.{event_type}
    (e.g., app.appointment.created)
```

---

## 8. MONITORING & OPERATIONS

```
Check Kafka Health:
$ curl http://localhost:8000/api/v1/health
{
  "status": "ok",
  "checks": {
    "db": "connected",
    "kafka": "connected"  ← Look for this
  }
}

List All Topics:
$ docker exec kafka kafka-topics --bootstrap-server kafka:29092 --list
app.appointment.created
app.appointment.cancelled
app.service.published
... (add more as needed)

View Consumer Group Status:
$ docker exec kafka kafka-consumer-groups \
    --bootstrap-server kafka:29092 \
    --group app-analytics \
    --describe

TOPIC                          PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
app.appointment.created        0          12345           12350           5
app.appointment.cancelled      0          567             567             0
app.service.published          0          89              89              0

(LAG = 0 means consumer is caught up)

View Recent Messages in Topic:
$ docker exec kafka kafka-console-consumer \
    --bootstrap-server kafka:29092 \
    --topic app.appointment.created \
    --from-beginning \
    --max-messages 5
```

---

## 9. KAFKA CONCEPTS MAPPING (For Supervisor)

| Kafka Concept | SmartHealth | Location |
|---|---|---|
| **Message** | Event (appointment.created) | app/services/healthcare_event_service.py |
| **Topic** | app.appointment.created | app/workers/analytics_consumer.py:_topics() |
| **Partition** | Partition 0 (single broker dev) | docker-compose.yml |
| **Offset** | Tracked in Kafka metadata | app/workers/analytics_consumer.py:run() |
| **Producer** | KafkaEventPublisher | app/integrations/kafka_client.py |
| **Consumer** | AnalyticsConsumer | app/workers/analytics_consumer.py |
| **Consumer Group** | app-analytics | app/core/settings.py |
| **Broker** | kafka:29092 container | docker-compose.yml |
| **Cluster** | Single broker (dev) → 3+ brokers (prod) | docker-compose.yml |

