"""Demonstrate durable appointment state across a Temporal worker restart.

First run submits one booking and saves its appointment ID:
    python tests/demo_tasks/temporal_test.py --new

Run it again while the worker is stopped to read PENDING. Start the worker,
then run it again to read CONFIRMED.
"""

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


async def request_json(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> tuple[int, dict]:
    response = await client.request(method, path, **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return response.status_code, body


async def login(client: httpx.AsyncClient, email: str, password: str) -> str:
    status_code, body = await request_json(client, "POST", "/auth/login", json={"email": email, "password": password})
    if status_code != 200:
        raise SystemExit(f"Login failed for {email}: HTTP {status_code} {body}")
    return body["access_token"]


async def find_or_create_slot(client: httpx.AsyncClient, patient_token: str, admin_email: str, admin_password: str, requested_slot_id: int | None) -> int:
    if requested_slot_id is not None:
        return requested_slot_id
    status_code, slots = await request_json(client, "GET", "/api/v1/slots?limit=100&offset=0", headers={"Authorization": f"Bearer {patient_token}"})
    if status_code != 200:
        raise SystemExit(f"Could not list slots: HTTP {status_code} {slots}")
    available = [slot for slot in slots.get("items", []) if slot.get("status") == "AVAILABLE"]
    if available:
        return available[0]["id"]

    admin_token = await login(client, admin_email, admin_password)
    provider_status, providers = await request_json(client, "GET", "/api/v1/providers?limit=1&offset=0", headers={"Authorization": f"Bearer {admin_token}"})
    service_status, services = await request_json(client, "GET", "/api/v1/public/services?limit=1&offset=0")
    if provider_status != 200 or service_status != 200 or not providers.get("items") or not services.get("items"):
        raise SystemExit("No available slot found, and admin could not discover provider/service data.")
    start = datetime.now(timezone.utc) + timedelta(days=1)
    status_code, created = await request_json(
        client,
        "POST",
        "/api/v1/slots",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"provider_id": providers["items"][0]["id"], "service_id": services["items"][0]["id"], "status": "AVAILABLE", "start_datetime": start.isoformat(), "end_datetime": (start + timedelta(minutes=30)).isoformat()},
    )
    if status_code != 200:
        raise SystemExit(f"Admin could not create a slot: HTTP {status_code} {created}")
    print(f"Admin created test slot {created['id']}.")
    return created["id"]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://localhost:8000"))
    parser.add_argument("--slot-id", type=int)
    parser.add_argument("--email", default=os.getenv("PATIENT_EMAIL", "patient@example.com"))
    parser.add_argument("--password", default=os.getenv("PATIENT_PASSWORD", "secret123"))
    parser.add_argument("--admin-email", default=os.getenv("ADMIN_EMAIL", "admin@example.com"))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", "secret123"))
    parser.add_argument("--new", action="store_true", help="Submit a new booking and replace saved state")
    args = parser.parse_args()

    state_file = Path(__file__).with_name(".temporal_test_state.json")
    booking_key = os.getenv("TEMPORAL_TEST_BOOKING_KEY", "temporal-single-booking-demo")
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=30) as client:
        token = await login(client, args.email, args.password)
        if state_file.exists() and not args.new:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            status_code, state = await request_json(client, "GET", f"/api/v1/appointments/{saved['appointment_id']}/state", headers={"Authorization": f"Bearer {token}"})
            if status_code != 200:
                raise SystemExit(f"Status check failed: HTTP {status_code} {state}")
            print(f"Appointment {saved['appointment_id']} for slot {saved['slot_id']}: {state['status']}")
            print("Status read from the database through the appointment status endpoint.")
            return

        if args.new:
            booking_key = f"{booking_key}-{uuid.uuid4()}"
        slot_id = await find_or_create_slot(client, token, args.admin_email, args.admin_password, args.slot_id)
        status_code, booking = await request_json(client, "POST", "/api/v1/appointments", headers={"Authorization": f"Bearer {token}", "Idempotency-Key": booking_key}, json={"slot_id": slot_id})
        if status_code not in {200, 202}:
            raise SystemExit(f"Booking request failed: HTTP {status_code} {booking}")
        state_file.write_text(json.dumps({"appointment_id": booking["id"], "slot_id": slot_id, "booking_key": booking_key}, indent=2), encoding="utf-8")
        print(f"Booking accepted: appointment {booking['id']} is {booking['status']}.")
        print(f"Saved state in {state_file.name}. Stop/restart the worker, then run this command again.")


if __name__ == "__main__":
    asyncio.run(main())
