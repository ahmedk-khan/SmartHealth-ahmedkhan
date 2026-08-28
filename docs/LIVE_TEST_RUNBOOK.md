# SmartHealth Live Test Runbook

Use this document during a mentor or Zoom demonstration. Swagger is available at:

```text
http://localhost:8000/docs
```

The API base URL is `http://localhost:8000`. All `/api/v1` endpoints require a JWT unless noted otherwise.

## 1. Start The Stack

From the repository root:

```powershell
docker compose up -d

docker compose ps
```

For application code or `.env` changes:

```powershell
docker compose up -d --force-recreate api temporal-worker
```

Open Swagger and click **Authorize**. Use the access token returned by `/auth/login`.

Useful demo accounts seeded by the application:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@example.com` | `secret123` |
| Patient | `patient@example.com` | `secret123` |
| Provider | `provider@example.com` | `secret123` |

## 2. Login

Swagger endpoint:

```text
POST /auth/login
```

Request body:

```json
{
  "email": "admin@example.com",
  "password": "secret123"
}
```

Save `access_token`. Repeat with `patient@example.com` when testing patient actions.

## 3. Create Organization Data

These steps are needed only when demonstrating creation from an empty database.

### Create department

```text
POST /api/v1/departments
```

```json
{
  "name": "Cardiology Demo",
  "description": "Heart care and cardiac examinations"
}
```

Save the returned department `id` as `DEPARTMENT_ID`.

### Create provider profile

First register a provider if one does not exist:

```text
POST /auth/register
```

```json
{
  "email": "demo.provider@example.com",
  "password": "secret123",
  "role": "provider"
}
```

Login as the provider or use the admin token. Then create the profile:

```text
POST /api/v1/providers
```

```json
{
  "user_id": 2,
  "bio": "Cardiology demo provider",
  "specialty": "Cardiology",
  "department_id": 1
}
```

Use the actual provider user and department IDs. Save the returned provider `id` as `PROVIDER_ID`.

### Create service

```text
POST /api/v1/services
```

```json
{
  "name": "Cardiac Examination",
  "description": "Clinical examination for heart and cardiovascular concerns.",
  "specialty": "Cardiology",
  "preparation_instructions": "Bring current medication and medical history.",
  "department_id": 1,
  "price": "150.00",
  "is_published": false
}
```

Save the returned service `id` as `SERVICE_ID`.

### Publish service

```text
POST /api/v1/services/{SERVICE_ID}/publish
```

Expected response: `202 Accepted` with a workflow ID.

Check the Temporal publication status:

```text
GET /api/v1/services/{SERVICE_ID}/publish-status
```

Repeat until the status is `PUBLISHED` and the stage is complete. This workflow validates, structures, chunks, embeds, and persists the service content.

## 4. Create A Schedule Slot

Use an admin, front-desk, or provider token:

```text
POST /api/v1/slots
```

```json
{
  "provider_id": 1,
  "service_id": 1,
  "status": "AVAILABLE",
  "start_datetime": "2026-09-01T10:00:00Z",
  "end_datetime": "2026-09-01T10:30:00Z"
}
```

Save the returned slot `id` as `SLOT_ID`.

Patients can see available slots with:

```text
GET /api/v1/slots?limit=100&offset=0
```

## 5. Normal Appointment Booking

Use the patient token:

```text
POST /api/v1/appointments
```

Header:

```text
Idempotency-Key: live-booking-001
```

Body:

```json
{
  "slot_id": 1
}
```

With asynchronous booking enabled, expected response:

```json
{
  "id": 1,
  "slot_id": 1,
  "status": "PENDING",
  "visit_status": "NOT_STARTED"
}
```

Save the appointment `id` as `APPOINTMENT_ID`.

Check the status:

```text
GET /api/v1/appointments/{APPOINTMENT_ID}/state
```

Expected progression:

```text
PENDING -> CONFIRMED
```

The Temporal saga performs validation, atomic slot reservation, appointment creation/update, billing pre-check, reminder scheduling, and confirmation.

## 6. Idempotency Test

Send the same request twice with the same patient and the same header:

```text
Idempotency-Key: live-booking-001
```

```json
{
  "slot_id": 1
}
```

Both requests must refer to the same appointment ID. The database must contain only one appointment for the booking key.

Do not generate a new idempotency key for a retry. A new key represents a new booking operation.

## 7. Five-Request Slot Race

This is the concurrency proof. It creates five temporary patients, finds or creates an available slot, submits five concurrent bookings, and asserts one successful booking.

Run from the repository root:

```powershell
python tests/demo_tasks/race_demo.py
```

Expected summary:

```text
Summary: 1 confirmed, 4 conflict responses
PASS: slot ... produced exactly one CONFIRMED appointment.
```

The database invariant is:

```text
One slot -> one appointment -> one CONFIRMED booking
```

The reservation is protected by an atomic update that only changes a slot whose status is still `AVAILABLE`.

## 8. Worker Restart Recovery

This test demonstrates one booking operation across multiple terminal runs. The appointment ID is saved in `tests/demo_tasks/.temporal_test_state.json`.

Ensure these values exist in `.env`:

```env
ASYNC_BOOKING_ENABLED=true
BOOKING_WORKFLOW_TIMEOUT_MINUTES=30
```

Reload the application services:

```powershell
docker compose up -d --force-recreate api temporal-worker
```

### First run

```powershell
python tests/demo_tasks/temporal_test.py --new
```

Expected:

```text
Booking accepted: appointment 10 is PENDING.
Saved state in .temporal_test_state.json.
```

Now stop only the worker:

```powershell
docker compose stop temporal-worker
```

### Second run while worker is stopped

```powershell
python tests/demo_tasks/temporal_test.py
```

Expected:

```text
Appointment 10 for slot 20: PENDING
Status read from the database through the appointment status endpoint.
```

Start the worker again:

```powershell
docker compose start temporal-worker
```

### Third run after recovery

```powershell
python tests/demo_tasks/temporal_test.py
```

Expected:

```text
Appointment 10 for slot 20: CONFIRMED
Status read from the database through the appointment status endpoint.
```

The appointment ID must remain the same in all runs. This proves Temporal resumed the existing workflow and did not create a second appointment.

Watch worker logs in a separate terminal:

```powershell
docker compose logs -f --since 2m temporal-worker
```

## 9. Billing Compensation

Enable the failure switch in `.env`:

```env
BILLING_FORCE_FAILURE=true
```

Reload API and worker:

```powershell
docker compose up -d --force-recreate api temporal-worker
```

Book a fresh available slot with a new idempotency key. The saga should reserve the slot, fail at billing, then compensate.

Expected final state:

```text
Appointment: CANCELLED
Slot: AVAILABLE
```

Verify the slot in Swagger:

```text
GET /api/v1/slots?limit=100&offset=0
```

After the demonstration, restore normal behavior:

```env
BILLING_FORCE_FAILURE=false
```

Then recreate the application services again.

## 10. Cancel And Waitlist

Cancel a confirmed appointment:

```text
POST /api/v1/appointments/{APPOINTMENT_ID}/cancel
```

Expected result:

```text
Appointment status: CANCELLED
Slot status: AVAILABLE
```

To join a waitlist for a reserved slot, use another patient token:

```text
POST /api/v1/appointments/waitlist/{SLOT_ID}
```

After cancellation, the oldest waiting patient is promoted according to the waitlist policy.

## 11. Visit Lifecycle

The appointment must be `CONFIRMED`.

Check in as authorized staff or provider:

```text
POST /api/v1/appointments/{APPOINTMENT_ID}/visit/check-in
```

Start the visit as a provider:

```text
POST /api/v1/appointments/{APPOINTMENT_ID}/visit/start
```

Complete the visit as a provider:

```text
POST /api/v1/appointments/{APPOINTMENT_ID}/visit/complete
```

Expected visit progression:

```text
NOT_STARTED -> CHECKED_IN -> IN_PROGRESS -> COMPLETED
```

## 12. Analytics And Logs

Use an admin or front-desk token:

```text
GET /api/v1/analytics/summary
```

For reconciliation:

```text
GET /api/v1/analytics/reconcile
```

Follow a booking across API and worker logs with its correlation ID:

```powershell
docker compose logs -f --since 10m api temporal-worker | Select-String "correlation_id"
```

Useful service checks:

```powershell
docker compose ps
docker compose logs --tail 100 api
docker compose logs --tail 100 temporal-worker
```

## 13. Final Evidence Checklist

A complete demonstration should show:

- Service publication reaches `PUBLISHED` and content chunks are embedded.
- Normal booking reaches `CONFIRMED`.
- Five concurrent bookings produce one success and four conflicts.
- Repeating one idempotency key produces one appointment.
- Billing failure ends with a cancelled appointment and released slot.
- Worker stop shows the same appointment as `PENDING`.
- Worker restart changes that same appointment to `CONFIRMED`.
- Cancellation releases the slot and handles the waitlist.
- Visit status reaches `COMPLETED`.
- Analytics and logs expose the resulting state and correlation ID.
