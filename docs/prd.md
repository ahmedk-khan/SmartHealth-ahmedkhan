# SmartHealth Product Requirements

## 1. Product purpose

SmartHealth is a healthcare scheduling and operations demonstration. It lets staff configure providers, departments, services, and discrete appointment slots. Patients can discover published services, book appointments safely during contention, follow a validated visit lifecycle, and receive consistent state and billing outcomes.

The system is scoped to one clinic and demonstrates authorization, transactional persistence, durable Temporal workflows, atomic slot claims, bounded background retries, event-driven analytics, and traceable logs.

## 2. Use cases

1. Staff register a provider, assign a department and specialty, create a service, publish it, and verify searchable content chunks.
2. A patient lists available slots and submits a booking. The saga validates eligibility, atomically reserves the slot, performs billing pre-check, schedules a reminder, and confirms the appointment.
3. Multiple patients race for one slot. Exactly one request succeeds because the database conditional update is authoritative.
4. A client retries a booking with the same idempotency key. The original appointment returns without another appointment or billing row.
5. A forced billing failure compensates the saga, preserves history, releases the slot, and allows a waiting patient to be promoted.
6. Front desk staff check in, start, and complete a visit. Invalid jumps and repeated transitions are rejected or idempotent.
7. Operators reconcile analytics and follow a booking across API, Temporal, Celery, and Kafka logs by correlation ID.

## 3. Functional requirements

- Authenticate users with bcrypt password hashes and JWT access tokens.
- Support patient, provider, front_desk, and admin roles with server-side PHI authorization.
- Manage departments, provider profiles, specialties, services, schedules, slots, appointments, billing, visits, and waitlists.
- Expose authenticated, paginated catalog and schedule APIs; patients see only published services and available slots.
- Publish service content through Temporal activities: validate, structure, chunk, embed, and persist.
- Run booking as a Temporal saga with validation, atomic reservation, billing, reminder, confirmation, and compensation activities.
- Record appointment status history and domain audit records for operational changes.
- Publish versioned Kafka envelopes and consume them idempotently into analytics tables.
- Retry transient Celery failures with bounded backoff and record terminal failures in `failed_jobs`.

## 4. Non-functional requirements

- No double booking under concurrent requests.
- Workflow activities are idempotent and chunk replacement is atomic at the service persistence boundary.
- Database mutations use repository methods and commit audit rows with the business mutation.
- Events carry identifiers and correlation metadata but no patient names, contact details, or clinical PHI.
- A fresh environment runs with `docker compose up --build`; tests run with `pytest -q` or `make test`.
- Health, metrics, structured JSON logs, and a recovery runbook are available.

## 5. Milestones

| Milestone | Delivered capability |
| --- | --- |
| Week 1 | Authentication, roles, departments, providers, services, slots, migrations |
| Week 2 | Published service chunks, semantic search, Temporal publishing workflow |
| Week 3 | Scheduling saga, atomic reservation, billing compensation, visits, Kafka/Celery analytics, observability |

## 6. Traceability

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Registration/login and hashes | `app/api/v1/endpoints/auth.py`, `app/core/security.py` | auth tests in `tests/integration/test_api.py` |
| Role and PHI authorization | `app/core/dependencies.py`, endpoint guards | protected endpoint tests |
| Provider/service/slot management | repositories and endpoints | API integration tests |
| Searchable published chunks | `app/workflows/service_publish.py`, `ContentChunkRepository` | chunk and publish tests |
| Durable service workflow | `ServicePublishWorkflow`, `app/temporal/worker.py` | Compose worker and publish path |
| Atomic booking | `SlotRepository.reserve_for_patient` | reservation tests; PostgreSQL concurrency demo |
| Booking idempotency | `app/core/idempotency.py` | idempotency test |
| Billing compensation | `BillingChecker`, saga compensation activities | forced-failure scenario |
| Cancellation and waitlist | `AppointmentRepository.cancel`, waitlist model | cancellation scenario |
| Visit lifecycle | appointment endpoint and repository transitions | visit lifecycle tests |
| Events and analytics | Kafka publisher and analytics consumer | replay/idempotency test |
| Celery failure handling | task retry policies and `FailedJobService` | task tests and runbook |
| Auditability | `AuditLog`, repository audit helper, status history | migration and mutation checks |

## 7. Out of scope

Multi-clinic tenancy, real payment/insurance integrations, clinical records, provider time-off rules, and production secret management are outside this demonstration.
