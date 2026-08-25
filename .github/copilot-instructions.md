# SmartHealth - GitHub Copilot Instructions

## Project Overview

SmartHealth is a backend application built with FastAPI, PostgreSQL, Celery, Redis, Kafka, Docker, and Temporal.

Follow the existing project architecture and patterns before introducing new ones.

---

## General Development Rules

- Inspect existing code before implementing new functionality.
- Reuse existing utilities, services, repositories, schemas, models, and error-handling patterns.
- Do not introduce duplicate functionality.
- Keep changes focused on the requested task.
- Do not unnecessarily change existing APIs or database schemas.
- Follow the existing project naming and folder conventions.
- Prefer clean, maintainable, production-ready code over quick hacks.

---

## FastAPI Rules

- Keep API/controllers thin.
- Do not put database queries directly inside route handlers.
- Use the repository/service layers for database access and business logic.
- Use FastAPI dependency injection where appropriate.
- Use Pydantic schemas for request and response validation.
- Return appropriate HTTP status codes.
- Follow the existing API response and error-handling conventions.

---

## Repository and Service Pattern

- Database queries should be implemented in repository classes/functions.
- Services should contain business logic.
- API routes should coordinate requests and responses rather than contain complex business logic.
- Reuse existing repositories before creating new ones.
- Keep database transaction boundaries explicit.

Preferred flow:

API Route
    ↓
Service
    ↓
Repository
    ↓
Database

---

## Error Handling

- Follow the project's existing `AppError` and exception-handling pattern.
- Do not silently swallow exceptions.
- Use meaningful error messages.
- Use appropriate HTTP status codes.
- Distinguish between validation errors, business errors, and unexpected system failures.
- Do not expose internal implementation details or sensitive information to API clients.

---

# Temporal Rules

## Workflow Determinism

Temporal Workflow code must remain deterministic.

Do not perform the following directly inside Workflow code:

- Database queries
- External API calls
- HTTP requests
- File-system operations
- Direct random number generation
- Direct system time access
- Other non-deterministic operations

Use Activities for external side effects and non-deterministic operations.

Workflow code should primarily orchestrate Activities.

---

## Activity Rules

Every production Activity must have an explicit timeout.

Use appropriate Temporal timeout configuration such as:

- `start_to_close_timeout`
- `schedule_to_close_timeout`
- `heartbeat_timeout` for appropriate long-running Activities

Do not create Activities without intentionally configuring their timeout.

---

## Retry Policies

Every Activity that can fail should have an intentional retry policy.

Do not allow Activities to retry indefinitely unless there is a documented reason.

Use retries for transient failures such as:

- Temporary database outage
- Network failure
- External service timeout
- Temporary service unavailability
- Rate limiting

Do not retry permanent business errors such as:

- Slot already booked
- Invalid appointment data
- User does not exist
- Unauthorized operation
- Invalid state transition
- Duplicate booking when it violates business rules
- Other permanent validation/business errors

---

## Non-Retryable Errors

Use Temporal `ApplicationError` with `non_retryable=True` for permanent business failures.

Example:

```python
raise ApplicationError(
    "Slot already booked",
    type="SlotAlreadyBooked",
    non_retryable=True,
)