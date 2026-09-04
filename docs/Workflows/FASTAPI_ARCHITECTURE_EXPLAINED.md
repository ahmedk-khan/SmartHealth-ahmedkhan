# FastAPI Architecture Guide for SmartHealth

This document is meant to help you explain the backend clearly in a meeting, even if you are more comfortable with Node.js or Express-style architecture.

The easiest way to think about this project is:

- FastAPI is the HTTP server
- SQLAlchemy is the database layer
- Services contain business logic
- Repositories handle database queries
- Workers handle background tasks
- Redis, Kafka, Temporal, and Celery are supporting systems for async work and distributed operations

You are not expected to memorize every file. Instead, you should know the architecture layers and the purpose of the main folders.

---

## 1. The big picture

This project is a healthcare platform backend. It manages:

- patients
- providers
- departments
- services
- slots
- appointments
- billing and visit flow
- notifications
- AI assistant features
- analytics and report generation

The system is built as a modular backend with a strong separation between:

- API layer
- auth and security layer
- domain services
- database access
- async workers
- monitoring and tracing

In Node.js terms, the closest analogy is:

- FastAPI = Express / Nest HTTP entry layer
- routers = route modules
- dependencies = auth guards / middleware / request-scoped context
- services = business logic layer
- repositories = data access layer
- models = database schema definitions
- workers = background job runners

---

## 2. What the main folders do

### app/

This is the core application code.

### app/main.py

This is the application entry file. It boots the FastAPI app and configures the server-level behavior.

Purpose:

- create the FastAPI instance
- register global middleware
- define health and metrics endpoints
- include the main router tree
- attach exception handlers for consistent API errors

Think of this as the startup file for the service.

Related:

- [app/core/app_factory.py](../..//app/core/app_factory.py)
- [app/api/__init__.py](../..//app/api/__init__.py)

### app/core/

This folder contains shared infrastructure that is used by many modules.

Important files:

- [app/core/app_factory.py](../..//app/core/app_factory.py) – creates the FastAPI app and configures startup lifecycle
- [app/core/settings.py](../..//app/core/settings.py) – loads environment variables and app config
- [app/core/dependencies.py](../..//app/core/dependencies.py) – shared dependency functions like authenticated user, role checks, permission checks
- [app/core/security.py](../..//app/core/security.py) – JWT token parsing and validation
- [app/core/exceptions.py](../..//app/core/exceptions.py) – custom API error handling
- [app/core/logging.py](../..//app/core/logging.py) – correlation ID and structured logging
- [app/core/metrics.py](../..//app/core/metrics.py) – Prometheus counters and histograms
- [app/core/rate_limit.py](../..//app/core/rate_limit.py) – request throttling

This is the infrastructure layer. If the question is “where is auth or error handling or logging defined?”, the answer is usually here.

### app/api/

This is the HTTP layer.

- [app/api/__init__.py](../..//app/api/__init__.py) registers the main route groups
- [app/api/v1/__init__.py](../..//app/api/v1/__init__.py) groups version 1 endpoints
- [app/api/v1/endpoints](../..//app/api/v1/endpoints) contains endpoint files by domain

Examples:

- appointments
- auth
- patients
- providers
- services
- slots
- analytics
- tasks
- assistant
- search
- health

The pattern is very similar to Express routers: each file exposes a Router and registers endpoints for a specific domain.

Example flow:

- route receives HTTP request
- route reads request body or query parameters
- route resolves dependencies such as database session and current user
- route calls a service class
- service does the business logic
- repository performs database operations

### app/db/

This defines the database connection layer.

- [app/db/__init__.py](../..//app/db/__init__.py) creates the SQLAlchemy engine and session factory

Purpose:

- connect to PostgreSQL or SQLite depending on environment
- provide database sessions to services and repositories
- centralize database configuration

This is the equivalent of a DB connection setup file in Node.js.

### app/models/

This folder contains ORM models. Each file maps to a database table.

Examples:

- user
- patient
- provider
- service
- slot
- appointment
- billing
- notification
- waitlist
- analytics models
- outbox and event records

These are SQLAlchemy models. They define:

- table name
- columns
- relationships
- enum values
- constraints

This is where the database schema structure lives conceptually.

### app/repositories/

This layer is responsible for database queries.

The repository pattern is used to keep SQL logic out of the service layer.

Examples:

- AppointmentRepository
- PatientRepository
- SlotRepository
- ServiceRepository
- AuthRepository
- AIInteractionRepository

Purpose:

- fetch entities by id
- list entities with filters
- create/update/delete records
- encapsulate SQLAlchemy query logic

This is typically where you would say: “the business logic calls the repository, not raw query objects in controllers.”

### app/services/

This is the business logic layer.

Examples:

- AppointmentService
- AuthService
- AssistantService
- SearchService
- UtilisationService
- HealthcareEventService
- BillingChecker

This layer decides what should happen, not just how to talk to the database.

Example responsibilities:

- validate user access
- check permissions
- validate slot availability
- apply business rules
- call workflows or background tasks
- publish domain events

This is the most important layer to understand conceptually if you are explaining the project to a supervisor.

### app/schemas/

This layer defines request and response validation shapes.

Using Pydantic, the project validates incoming payloads and structures responses.

Examples:

- user schemas
- domain schemas
- assistant schemas
- search schemas

Purpose:

- reject invalid requests early
- ensure consistent payload shape
- transform Python objects to API-friendly structures

This is the FastAPI equivalent of input validation in Node.js.

---

## 3. Authentication and authorization flow

This project is built around JWT-based auth and permission checks.

### Key files

- [app/core/dependencies.py](../..//app/core/dependencies.py)
- [app/core/security.py](../..//app/core/security.py)
- [app/api/v1/endpoints/auth.py](../..//app/api/v1/endpoints/auth.py)

### How it works conceptually

1. User logs in using email and password.
2. Backend validates credentials.
3. Backend issues a JWT token.
4. Every protected route receives the token via dependency injection.
5. The app decodes the token and fetches the user from the database.
6. The system checks role and permissions before allowing the action.

The permission pattern here is very important:

- get_current_user resolves the logged-in user
- require_role checks role-based access such as admin, provider, patient
- require_permission checks a domain permission like appointment read or service create

This is similar to Node.js middleware that runs before protected endpoints.

---

## 4. Typical request lifecycle

If you want a single explanation to use in a meeting, this is the one to remember:

1. Request enters FastAPI route.
2. Route validates the input body and path params.
3. Dependencies inject database session and current user.
4. The route calls a service class.
5. Service calls repository methods.
6. Repository executes SQLAlchemy queries against the database.
7. Domain rules are applied.
8. Response is serialized by Pydantic and returned to the client.

This is the standard layered architecture.

Example: appointment creation

- API route receives booking request
- auth dependency ensures the patient is logged in
- AppointmentService validates patient and slot
- a workflow is started to reserve slot and finalize the booking
- repository updates database state
- events are published
- response returns status to the client

---

## 5. Appointment booking workflow

This is the core business process and one of the most important flows to explain.

### Files involved

- [app/api/v1/endpoints/appointments.py](../..//app/api/v1/endpoints/appointments.py)
- [app/services/appointment_service.py](../..//app/services/appointment_service.py)
- [app/workers/temporal/workflows/appointment_saga.py](../..//app/workers/temporal/workflows/appointment_saga.py)
- [app/workers/temporal/activities/appointment_saga.py](../..//app/workers/temporal/activities/appointment_saga.py)

### Concept

The appointment flow is not a simple insert into one table. It is a saga-style workflow.

A saga is a sequence of steps that can be compensated if a later step fails.

The flow includes:

- validate patient and slot
- reserve slot
- create appointment record
- run billing pre-check
- schedule reminder
- confirm appointment
- emit event for downstream systems

Important idea:

If something fails after a reservation is made, the workflow compensates by releasing the slot and canceling the pending appointment instead of leaving the system in an inconsistent state.

This is similar to a transactional orchestration pattern in distributed systems.

---

## 6. What Temporal is used for

Temporal is used for long-running business workflows that need durability and replay-safe execution.

In this project, it is used for complex domain workflows like appointment booking and service publication.

Why not keep everything in the request thread?

- the process may involve multiple steps
- some steps need retry behavior
- some steps need compensation on failure
- the flow must be durable even if the API process restarts

In other words, Temporal acts like a workflow orchestrator for important business operations.

Think of it as:

- workflow = the process definition
- activity = the individual atomic step
- worker = the runtime that executes those activities

This is very different from a normal REST request where everything happens in one thread.

---

## 7. What Celery is used for

Celery handles background jobs and scheduled tasks.

### Main files

- [app/workers/celery_app.py](../..//app/workers/celery_app.py)
- [app/workers/celery](../..//app/workers/celery)

### Typical use cases

- scheduled reminder tasks
- reporting jobs
- analytics tasks
- outbox or event dispatch processing

Celery is not the main API path. It is the background task system.

If the API needs to queue something for later without blocking the user, Celery is the tool used.

This is the Node.js equivalent of a message queue or job queue pattern.

---

## 8. What Redis is used for

Redis is used for fast shared state and operational control.

Important uses in this project:

- idempotency keys for safe repeated booking requests
- AI request rate limiting
- caching assistant answers
- session or request metadata
- shared task broker support for Celery

This means Redis acts as a lightweight high-speed layer for operational coordination, not just as a cache.

### Important files

- [app/core/idempotency.py](../..//app/core/idempotency.py)
- [app/core/ai_controls.py](../..//app/core/ai_controls.py)
- [app/core/rate_limit.py](../..//app/core/rate_limit.py)

The core concept is: Redis helps protect the system from repeated requests, abuse, and expensive compute operations.

---

## 9. What Kafka is used for

Kafka is used for event-based communication and downstream processing.

The project publishes domain events such as appointments created, cancelled, or otherwise updated, and downstream consumers can react to those events.

This is useful for analytics and event-driven integrations.

Conceptually:

- producer publishes an event
- consumer processes the event asynchronously
- other services can react without being tightly coupled to the booking flow

This is a classic event-driven architecture piece.

---

## 10. What SQLAlchemy is doing

SQLAlchemy is the ORM layer used for database interactions.

It provides:

- model definitions
- query building
- session management
- transaction control
- database abstraction

This is the equivalent of TypeORM, Prisma, or Sequelize in Node.js projects.

The important architectural separation is:

- models describe the database schema
- repositories run the queries
- services apply the business rules

That separation is what keeps the project maintainable.

---

## 11. What Pydantic is doing

Pydantic is used for validation and schema modeling.

It ensures that:

- incoming request bodies match expected fields
- outputs are shaped consistently
- validation errors are returned cleanly

This is the FastAPI equivalent of request DTO validation in Node.js.

If you are explaining the backend in a meeting, a good sentence is:

“FastAPI uses Pydantic models to validate requests and serialise responses, so the API layer enforces shape and data quality before business logic runs.”

---

## 12. The AI assistant architecture

The project also includes a healthcare assistant with a safety layer.

### Relevant files

- [app/api/v1/endpoints/assistant.py](../..//app/api/v1/endpoints/assistant.py)
- [app/services/assistant_service.py](../..//app/services/assistant_service.py)
- [app/services/safety_service.py](../..//app/services/safety_service.py)
- [app/services/llm_provider.py](../..//app/services/llm_provider.py)

### Concept

The assistant is not just a raw LLM integration. It includes:

- request classification
- safety filtering
- retrieval of services or patient context
- citation generation
- audit logging of interactions
- rate limit protection
- prompt versioning

This is important because it shows the project is not only scheduling logic; it also includes healthcare-safe AI patterns.

---

## 13. Monitoring and operations

This project is designed to be observable.

### Key components

- structured logging with correlation IDs
- Prometheus metrics endpoint
- health checks
- middleware for request tracking
- background task logging

This helps answer operational questions like:

- which request is causing latency?
- which user or workflow triggered this event?
- how many appointments were created?
- what failed in the background worker?

This is especially valuable in a distributed system with Celery, Redis, Kafka, and Temporal.

---

## 14. Where to look when someone asks a specific question

If you are being asked: “Where is this logic handled?” here is the map.

### “Where is the HTTP endpoint defined?”
Answer: route files under [app/api/v1/endpoints](../..//app/api/v1/endpoints)

### “Where is the user auth logic?”
Answer: [app/core/dependencies.py](../..//app/core/dependencies.py), [app/core/security.py](../..//app/core/security.py), [app/api/v1/endpoints/auth.py](../..//app/api/v1/endpoints/auth.py)

### “Where is the actual business logic?”
Answer: [app/services](../..//app/services)

### “Where are the database queries?”
Answer: [app/repositories](../..//app/repositories)

### “Where are the database tables defined?”
Answer: [app/models](../..//app/models)

### “Where is the app startup and middleware configured?”
Answer: [app/main.py](../..//app/main.py) and [app/core/app_factory.py](../..//app/core/app_factory.py)

### “Where is the async workflow orchestration?”
Answer: [app/workers/temporal](../..//app/workers/temporal)

### “Where are scheduled tasks?”
Answer: [app/workers/celery](../..//app/workers/celery)

### “Where are background events handled?”
Answer: [app/workers/kafka](../..//app/workers/kafka)

---

## 15. The most important mindset to explain

The project is not a single monolithic API file. It is a layered backend with distinct concerns.

Use this mental model in meetings:

- API layer: receives requests
- dependencies: enforce auth and context
- services: enforce business rules
- repositories: query and persist data
- workers: run long-running tasks in the background
- infrastructure: Redis, Kafka, Celery, Temporal, metrics, logging

That is the real architectural story.

---

## 16. Short explanation you can say in a meeting

If your supervisor asks “What is this project doing?” you can say:

“This is a FastAPI-based healthcare scheduling backend. The API layer exposes endpoints for patients, providers, services, slots, and appointments. Each request goes through auth and validation, then business logic in service classes, then repository-level database access. For complex workflows like booking and cancellation, the app uses Temporal saga orchestration so steps can be retried and compensated safely. Redis handles idempotency and rate limiting, Celery handles background tasks and reports, and Kafka is used for event-driven downstream processing. The project also includes Prometheus metrics, structured logging, and AI assistant flows with safety checks.”

---

## 17. Quick comparison to Node.js concepts

If you want to map FastAPI to familiar Node.js concepts:

- FastAPI app = Express/Nest app
- APIRouter = route module
- Depends = middleware or guard
- Pydantic model = DTO / schema validation
- SQLAlchemy model = ORM entity
- Repository = data access layer
- Service = business logic
- Celery = queue worker
- Redis = cache / rate limit / idempotency store
- Temporal = workflow orchestrator
- Kafka = event bus

This makes it easier to explain what each part is doing without needing to memorize Python syntax.

---

## 18. Recommended way to prepare for the meeting

Before the meeting, make sure you can answer these questions confidently:

- What is the purpose of the root API bootstrap?
- What does each folder do in plain English?
- Where does authentication happen?
- Where is the booking workflow orchestrated?
- Why is Temporal used instead of simply doing everything inside the API request?
- What is the purpose of Redis in this project?
- What is the role of Celery and Kafka?
- Why are services and repositories separated?
- How do metrics and logs help with production operations?

If you can answer those clearly, you will sound very solid even without full Python familiarity.

---

## Final takeaway

This project is not just “Python code”; it is a distributed backend with a clean layered architecture:

- route handling
- auth and permissions
- business services
- database access
- orchestration workflows
- async jobs
- event-driven processing
- observability

That is the core story to tell.
