# Structured JSON Logging with Correlation ID Middleware

## Overview

This document describes the structured JSON logging system implemented across SmartHealth, providing complete end-to-end traceability through correlation IDs and request IDs propagated across HTTP requests, Celery tasks, Temporal workflows, and event streams.

## Architecture

### Core Components

#### 1. **Correlation ID Middleware** (`app/main.py`)
- Intercepts all HTTP requests
- Extracts or generates correlation ID from `X-Correlation-ID` header
- Extracts or generates request ID from `X-Request-ID` header
- Sets both values in context variables for thread-local access
- Returns correlation/request IDs in response headers for client tracking

#### 2. **JSON Logging Formatter** (`app/core/logging.py`)
- All log output is structured JSON with no newlines
- Automatically includes:
  - Timestamp (ISO 8601 UTC)
  - Log level
  - Logger name
  - Message (sanitized for PHI)
  - Correlation ID (from context)
  - Request ID (from context)
  - Custom extra fields (sanitized for PHI)
- PHI is automatically redacted from all log output

#### 3. **Celery Signal Handlers** (`app/celery_app.py`)
- **before_task_publish**: Attaches correlation ID to task headers before publishing
- **task_prerun**: Extracts correlation ID from task headers and sets context
- **task_postrun**: Logs task completion with correlation context
- **task_failure**: Logs task failures with correlation context
- All Celery task logs include correlation context

#### 4. **Temporal Activity Logging** (`app/workflows/temporal_logging.py`)
- Activities receive correlation_id and request_id in their input data
- `setup_activity_context()`: Extracts and sets correlation context for activities
- `log_activity_step()`: Logs activity steps with correlation context
- `log_activity_error()`: Logs activity errors with correlation context
- Enhanced workflow logging in `appointment_saga.py`

#### 5. **Event Service Correlation** (`app/services/healthcare_event_service.py`)
- Auto-captures correlation_id and request_id from context
- Ensures all published events include correlation metadata
- No need to manually pass correlation IDs when publishing events

#### 6. **Base Service Logging** (`app/services/base.py`)
- BaseService includes structured logging utilities
- `log_info()`, `log_warning()`, `log_error()`, `log_debug()` methods
- All service logs automatically include correlation context
- Used by AuthService, AppointmentService, and others

#### 7. **Event Envelopes** (`app/events/envelopes.py`)
- Standardized EventEnvelope structure for domain events
- EventMetadata includes:
  - event_id (UUID)
  - event_type
  - source
  - occurred_at (ISO 8601 UTC)
  - correlation_id
  - request_id
  - workflow_id (optional, for Temporal)
  - user_id (optional, for audit)
- EventEnvelopeFactory for creating typed events

## Data Flow

### HTTP Request → Response

```
HTTP Request (with X-Correlation-ID, X-Request-ID headers)
    ↓
CorrelationIdMiddleware
    ├─ Extract or generate correlation_id
    ├─ Extract or generate request_id
    ├─ Set context variables
    └─ Store in request.state
    ↓
Route Handler
    ├─ Context variables available
    └─ All logging includes correlation context
    ↓
HTTP Response
    └─ Return X-Correlation-ID, X-Request-ID in headers
```

### HTTP Request → Celery Task

```
HTTP Request (with X-Correlation-ID header)
    ↓
Service calls celery_app.delay()
    ↓
before_task_publish signal
    └─ Attach correlation_id to task headers
    ↓
Task published to broker
    ↓
task_prerun signal
    ├─ Extract correlation_id from headers
    └─ Set context variables
    ↓
Task execution
    └─ All logging includes correlation context
    ↓
task_postrun signal
    └─ Log completion with correlation
```

### HTTP Request → Temporal Workflow → Activity

```
HTTP Request (with X-Correlation-ID header)
    ↓
Service calls run_appointment_saga(workflow_payload)
    ↓
Workflow receives correlation_id in payload
    ↓
Workflow.execute_activity(activity_data)
    ├─ Pass correlation_id in activity_data
    ↓
Activity execution
    ├─ setup_activity_context() sets context
    └─ All logging includes correlation context
    ↓
Activity completion
    └─ Correlation context maintained across saga
```

### Event Publishing with Correlation

```
Service publishes event
    ↓
healthcare_event_service.publish_appointment_event(...)
    ├─ Auto-captures correlation_id from context
    ├─ Auto-captures request_id from context
    └─ Passes to KafkaEventPublisher
    ↓
Event envelope created:
{
  "event_id": "uuid",
  "event_type": "appointment.created",
  "occurred_at": "2026-08-16T...",
  "source": "smarthealth-api",
  "schema_version": 1,
  "correlation_id": "...",
  "request_id": "...",
  "workflow_id": "...",
  "appointment_id": 123,
  ...
}
    ↓
Published to Kafka
```

## Usage Examples

### Automatic Logging in Services

```python
from app.services.base import BaseService

class MyService(BaseService):
    def do_something(self, entity_id: int):
        # Correlation ID is automatically included
        self.log_info(
            "Processing entity",
            operation="do_something",
            data={"entity_id": entity_id}
        )
        
        # Logging output (JSON):
        # {"timestamp":"2026-08-16T...","level":"INFO","logger":"...",
        #  "message":"Processing entity","correlation_id":"abc123",
        #  "request_id":"def456","operation":"do_something","entity_id":123}
```

### Publishing Events with Correlation

```python
from app.services.healthcare_event_service import HealthcareEventService

event_service = HealthcareEventService()

# No need to manually pass correlation_id - it's auto-captured
event_service.publish_appointment_event(
    "appointment.created",
    appointment_id=123,
    patient_id=456,
    status="CONFIRMED"
)

# Event will include:
# "correlation_id": "abc123" (auto-captured from context)
# "request_id": "def456" (auto-captured from context)
```

### Temporal Activity with Logging

```python
from app.workflows.temporal_logging import setup_activity_context

@activity.defn
async def my_activity(activity_data: dict[str, Any]) -> dict[str, Any]:
    # Extract and set correlation context
    setup_activity_context(activity_data, "my_activity")
    
    # Logs automatically include correlation context
    logger.info("Activity started")
    
    # Activity processing...
    
    return result
```

### Using Event Envelopes

```python
from app.events.envelopes import EventEnvelopeFactory

# Create typed event with automatic correlation
envelope = EventEnvelopeFactory.create_appointment_event(
    event_type="appointment.created",
    appointment_id=123,
    patient_id=456,
    status="CONFIRMED"
)

# Envelope includes:
# metadata: {
#   "correlation_id": "abc123",
#   "request_id": "def456",
#   "workflow_id": "...",
#   ...
# }
# data: { appointment_id: 123, ... }
```

## PHI Sanitization

All personally identifiable information (PHI) is automatically redacted from logs:

**Redacted keywords:**
- name, email, phone, mobile
- dob, date_of_birth
- address, street, city, postal_code, ssn
- diagnosis, symptoms, notes
- medical_history, insurance, allergies
- patient_name, provider_name
- Any field ending with "_name"

**Example:**
```python
logger.info("User data", extra={"user_name": "John Doe", "age": 30})

# Output (sanitized):
# {"message":"User data","age":30,"user_name":"[REDACTED]",...}
```

## Observability

### Tracing Requests

Use correlation_id to trace a request through the entire system:

1. **HTTP Response Headers**
   ```
   X-Correlation-ID: abc123def456
   X-Request-ID: xyz789
   ```

2. **Search Logs**
   ```
   correlation_id=abc123def456
   ```

3. **Check Events**
   ```
   {"metadata":{"correlation_id":"abc123def456",...},...}
   ```

4. **Inspect Celery Tasks**
   ```
   correlation_id=abc123def456 task_id=...
   ```

5. **Review Temporal Workflows**
   ```
   correlation_id=abc123def456 workflow_id=...
   ```

### Client Correlation

Clients can provide their own correlation ID:

```bash
curl -H "X-Correlation-ID: my-trace-id" \
     -H "X-Request-ID: my-request-id" \
     https://smarthealth/api/v1/appointments
```

Server will propagate these through all downstream systems.

## Configuration

### Logging Level

Configure in `app/core/logging.py`:

```python
# In main.py
configure_logging(level=logging.INFO)  # or DEBUG, WARNING, ERROR
```

### Disable JSON Logging

For local development, you can configure text logging:

```python
# Configure before starting app
configure_logging()  # Uses JSON by default
```

### Kafka Event Correlation

Events published to Kafka include full correlation metadata:

```python
event_service.publish_appointment_event(
    "appointment.created",
    appointment_id=123,
    # No need to pass correlation_id - auto-captured
)
```

## Best Practices

1. **Always use context-aware logging methods**
   ```python
   # Good
   self.log_info("Message", operation="op_name", data={...})
   
   # Avoid
   logger.info("Message")  # Missing context
   ```

2. **Use operation names for grouping**
   ```python
   self.log_info("Processing", operation="create_appointment")
   self.log_error("Failed", operation="create_appointment")
   ```

3. **Include relevant entity IDs**
   ```python
   self.log_info(
       "Status changed",
       operation="transition_status",
       data={"appointment_id": 123, "status": "CONFIRMED"}
   )
   ```

4. **Avoid logging PHI directly**
   ```python
   # Good - using redacted placeholders
   self.log_info("Login attempt", data={"email": "[REDACTED]"})
   
   # Avoid
   self.log_info("Login", data={"email": user.email})  # PHI leaked
   ```

5. **Pass correlation context through async boundaries**
   ```python
   # Temporal activities
   await workflow.execute_activity(
       my_activity,
       {**data, "correlation_id": get_correlation_id()}
   )
   ```

6. **Use event envelopes for event publishing**
   ```python
   # Good - structured with metadata
   envelope = EventEnvelopeFactory.create_appointment_event(...)
   
   # Avoid
   publish_raw_data({...})  # Missing correlation
   ```

## Testing

### Verify Correlation Propagation

```python
def test_appointment_creation_has_correlation():
    # Make request with correlation ID
    response = client.post(
        "/api/v1/appointments",
        json={...},
        headers={"X-Correlation-ID": "test-123"}
    )
    
    # Check response has same correlation ID
    assert response.headers["X-Correlation-ID"] == "test-123"
```

### Verify Log Correlation

```python
def test_logs_include_correlation():
    with caplog.at_level(logging.INFO):
        service.do_something()
    
    logs = caplog.text
    assert '"correlation_id":"test-123"' in logs
```

## Troubleshooting

### Missing Correlation ID in Logs

1. **Check context is set**
   ```python
   from app.core.logging import get_correlation_id
   print(get_correlation_id())  # Should not be None
   ```

2. **Verify middleware is registered**
   - CorrelationIdMiddleware should be added to app

3. **Check logger is using JSONFormatter**
   - Verify configure_logging() was called

### Correlation ID Not Propagating to Celery

1. **Ensure task is published from request context**
   - Celery must capture context before task is sent

2. **Check signals are registered**
   - Verify celery_app.py has signal handlers

3. **Inspect task headers**
   - Monitor Celery to verify headers are attached

### Temporal Activities Missing Correlation

1. **Pass correlation_id in activity input**
   ```python
   await workflow.execute_activity(
       activity,
       {**data, "correlation_id": get_correlation_id()}
   )
   ```

2. **Call setup_activity_context() early**
   - Must be called before any logging

3. **Verify context vars aren't reset**
   - Check for reset_correlation_id() calls
