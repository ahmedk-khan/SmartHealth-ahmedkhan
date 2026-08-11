# SmartHealth

SmartHealth is a FastAPI-based healthcare scheduling platform with:

- email/password authentication
- role-based access control for patients, providers, front-desk staff, and admins
- department and provider onboarding
- service publishing and public discovery
- slot management, booking, and appointment workflows
- billing pre-checks and visit lifecycle tracking

## What’s included in Week 2

The current implementation includes:

- service status handling with publish/unpublish validation and conflict responses
- service publishing via a Temporal-oriented workflow with activities that validate, structure, chunk, and mark services as published
- publish status querying through `POST /services/{id}/publish` and `GET /services/{id}/publish-status`
- slot reservation using an atomic conditional update to prevent double-booking
- appointment domain models, status history, and billing records
- booking idempotency using the `Idempotency-Key` header with Redis-backed storage
- appointment saga-style flow for booking, billing, reminders, and confirmation with compensation on failure
- visit lifecycle transitions for `CHECKED_IN`, `IN_PROGRESS`, and `COMPLETED`

## Quick start

1. Copy the environment file:
   ```bash
   copy .env.example .env
   ```
2. Start the supporting services with Docker Compose:
   ```bash
   docker compose up -d postgres temporal
   ```
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Apply the database schema (Alembic is configured):
   ```bash
   alembic upgrade head
   ```
5. Start the FastAPI app:
   ```bash
   uvicorn app.main:app --reload
   ```
6. Start the Temporal worker for workflow execution:
   ```bash
   python -m app.workers.service_publish_worker
   ```

## API overview

### Auth

- `POST /auth/register`
  - body: `email`, `password`, `role`
  - roles: `patient`, `provider`, `front_desk`, `admin`

- `POST /auth/login`
  - body: `email`, `password`
  - returns an access token

### Health

- `GET /health`
  - returns service status

### Departments

- `POST /api/v1/departments`
  - roles: `admin`, `front_desk`
  - body: `name`, optional `description`

- `GET /api/v1/departments`
  - requires authentication

### Providers

- `POST /api/v1/providers`
  - roles: `provider`, `admin`, `front_desk`
  - body: `bio`, `department_id`
  - links the provider record to the authenticated user

- `GET /api/v1/providers`
  - requires authentication

- `GET /api/v1/providers/{provider_id}/slots`
  - returns the provider’s slot schedule

### Services

- `POST /api/v1/services`
  - roles: `provider`, `admin`, `front_desk`
  - body: `name`, `description`, `department_id`, `is_published`

- `POST /api/v1/services/{service_id}/publish`
  - roles: `provider`, `admin`, `front_desk`
  - starts the publish workflow and returns `202 Accepted` with `workflow_id`

- `GET /api/v1/services/{service_id}/publish-status`
  - returns the current workflow status

- `GET /api/v1/services`
  - returns published services only

### Slots

- `POST /api/v1/slots`
  - roles: `provider`, `admin`, `front_desk`
  - body: `provider_id`, `service_id`, `status`, `start_datetime`, `end_datetime`

- `POST /api/v1/slots/{slot_id}/reserve`
  - roles: `patient`
  - atomically reserves an available slot

- `GET /api/v1/slots`
  - patients see only currently available slots

### Appointments

- `POST /api/v1/appointments`
  - roles: `patient`
  - body: `slot_id`
  - supports `Idempotency-Key` for duplicate-safe booking requests

- `GET /api/v1/appointments/{appointment_id}/state`
  - returns the appointment status and slot reference

- `POST /api/v1/appointments/{appointment_id}/cancel`
  - cancels the appointment and releases the slot

- `POST /api/v1/appointments/{appointment_id}/reschedule`
  - moves the appointment to a different slot

- `POST /api/v1/appointments/{appointment_id}/billing/pre-check`
  - creates or returns the billing pre-check record

- `POST /api/v1/appointments/{appointment_id}/visit/check-in`
- `POST /api/v1/appointments/{appointment_id}/visit/start`
- `POST /api/v1/appointments/{appointment_id}/visit/complete`
  - manage the visit lifecycle in an idempotent way

### Public

- `GET /api/v1/public/services`
  - query params: `search`, `department_id`, `limit`, `offset`
  - returns published services without authentication

## Seed data

Use the seeding helper to populate sample users and data:

```bash
docker compose run --rm api python -m app.seed
```

Seeded accounts include:

- `admin@example.com` / `secret123`
- `provider@example.com` / `secret123`
- `patient@example.com` / `secret123`

## Testing

Run the API test suite with:

```bash
pytest -q
```

## Notes

- The app uses `.env` for database, JWT, Redis, and Temporal configuration.
- The API mounts auth routes under `/auth` and versioned business routes under `/api/v1`.
- The provider creation endpoint uses the current authenticated user rather than a user-supplied `user_id`.
