# SmartHealth

SmartHealth is a FastAPI-based healthcare scheduling service with:

- email/password authentication
- role-based access control (`patient`, `provider`, `front_desk`, `admin`)
- providers, departments, services, and appointment slots
- PostgreSQL persistence via SQLAlchemy

## Quick start

1. Copy the environment file:
   ```bash
   copy .env.example .env
   ```
2. Start PostgreSQL with Docker Compose:
   ```bash
   docker compose up -d postgres
   ```
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the database schema creation (or Alembic migrations if configured):
   ```bash
   python -m app.db
   ```
   or
   ```bash
   alembic upgrade head
   ```
5. Start the FastAPI app:
   ```bash
   uvicorn app.main:app --reload
   ```

## API endpoints

### Auth

- `POST /auth/register`
  - request body: `email`, `password`, `role`
  - roles: `patient`, `provider`, `front_desk`, `admin`

- `POST /auth/login`
  - request body: `email`, `password`
  - response: `access_token`

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
  - the endpoint creates a provider record for the current user

- `GET /api/v1/providers`
  - requires authentication

- `GET /api/v1/providers/{provider_id}/slots`
  - requires authentication
  - returns slot schedule for the provider

### Services

- `POST /api/v1/services`
  - roles: `provider`, `admin`, `front_desk`
  - body: `name`, `description`, `department_id`, `is_published`

- `GET /api/v1/services`
  - returns only published services

### Slots

- `POST /api/v1/slots`
  - roles: `provider`, `admin`, `front_desk`
  - body: `provider_id`, `service_id`, `status`, `start_datetime`, `end_datetime`

- `GET /api/v1/slots`
  - returns slots, patients see only available slots

### Public

- `GET /api/v1/public/services`
  - query params: `search`, `department_id`, `limit`, `offset`
  - returns published services without auth

## Seed data

Use the seeding helper to populate sample users and data:

```bash
docker compose run --rm api python -m app.seed
```

Seeded accounts include:

- `admin@example.com` / `secret123`
- `provider@example.com` / `secret123`
- `patient@example.com` / `secret123`

## Notes

- The app uses `.env` for database and JWT configuration.
- The API mounts auth routes under `/auth` and versioned business routes under `/api/v1`.
- The provider creation endpoint ignores a user-provided `user_id`; it uses the current authenticated user.
