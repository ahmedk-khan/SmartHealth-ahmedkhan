# SmartHealth

A FastAPI health scheduling service with auth, user roles, provider schedules, and slot booking.

## Setup

1. Copy `.env.example` to `.env`.
2. Start PostgreSQL and Redis with Docker Compose:
   ```bash
   docker compose up -d postgres redis
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run Alembic migrations:
   ```bash
   alembic upgrade head
   ```
5. Start the app:
   ```bash
   uvicorn app.main:app --reload
   ```

## API

- `GET /health`
- `POST /auth/register`
- `POST /auth/login`
