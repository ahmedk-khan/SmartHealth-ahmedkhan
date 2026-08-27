"""Demonstrate that concurrent booking requests cannot double-book a slot.

Run from the project directory in the terminal"
    python tests/demo_tasks/race_demo.py

The script creates five temporary patients, races their requests against one


available slot, and exits with an error unless exactly one booking succeeds.
"""

import argparse
import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx


@dataclass
class BookingResult:
    patient: str
    status_code: int
    body: dict | str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://localhost:8000"))
    parser.add_argument("--slot-id", type=int, help="Use a specific available slot instead of auto-discovery")
    parser.add_argument("--admin-email", default=os.getenv("ADMIN_EMAIL", "admin@example.com"))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", "secret123"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("RACE_DEMO_TIMEOUT_SECONDS", "300")))
    return parser.parse_args()


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
        raise RuntimeError(f"Login failed for {email}: HTTP {status_code} {body}")
    return body["access_token"]


async def register_patient(client: httpx.AsyncClient, email: str) -> None:
    status_code, body = await request_json(
        client,
        "POST",
        "/auth/register",
        json={"email": email, "password": "secret123", "role": "patient", "first_name": "Race", "last_name": "Demo"},
    )
    if status_code not in {200, 201}:
        raise RuntimeError(f"Patient registration failed: HTTP {status_code} {body}")


async def find_available_slot(client: httpx.AsyncClient, admin_token: str, requested_slot_id: int | None) -> int:
    if requested_slot_id is not None:
        return requested_slot_id
    status_code, body = await request_json(
        client,
        "GET",
        "/api/v1/slots",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"limit": 100, "offset": 0},
    )
    if status_code != 200:
        raise RuntimeError(f"Could not list slots: HTTP {status_code} {body}")
    available = [slot for slot in body.get("items", []) if slot.get("status") == "AVAILABLE"]
    if not available:
        provider_status, providers = await request_json(
            client,
            "GET",
            "/api/v1/providers",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"limit": 1, "offset": 0},
        )
        service_status, services = await request_json(
            client,
            "GET",
            "/api/v1/public/services",
            params={"limit": 1, "offset": 0},
        )
        if provider_status != 200 or service_status != 200 or not providers.get("items") or not services.get("items"):
            raise RuntimeError("No available slot found, and a provider/service could not be discovered.")
        start = datetime.now(timezone.utc) + timedelta(days=1)
        slot_status, created = await request_json(
            client,
            "POST",
            "/api/v1/slots",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "provider_id": providers["items"][0]["id"],
                "service_id": services["items"][0]["id"],
                "status": "AVAILABLE",
                "start_datetime": start.isoformat(),
                "end_datetime": (start + timedelta(minutes=30)).isoformat(),
            },
        )
        if slot_status != 200:
            raise RuntimeError(f"Could not create a demo slot: HTTP {slot_status} {created}")
        print(f"\nNo available slot found; created temporary slot {created['id']}.\n")
        return created["id"]
    return available[0]["id"]


async def book(client: httpx.AsyncClient, patient: str, token: str, slot_id: int) -> BookingResult:
    status_code, body = await request_json(
        client,
        "POST",
        "/api/v1/appointments",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"race-demo-{patient}"},
        json={"slot_id": slot_id},
    )
    if status_code != 202 or body.get("status") != "PENDING":
        return BookingResult(patient, status_code, body)

    appointment_id = body["id"]
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        state_code, state = await request_json(
            client,
            "GET",
            f"/api/v1/appointments/{appointment_id}/state",
            headers={"Authorization": f"Bearer {token}"},
        )
        if state_code != 200:
            return BookingResult(patient, state_code, state)
        if state["status"] == "CONFIRMED":
            return BookingResult(patient, 202, state)
        if state["status"] in {"CANCELLED", "COMPLETED", "NO_SHOW"}:
            return BookingResult(patient, 409, state)
    return BookingResult(patient, 504, {"error": "booking status timed out", "appointment_id": appointment_id})


async def main() -> None:
    args = parse_args()
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        admin_token = await login(client, args.admin_email, args.admin_password)
        slot_id = await find_available_slot(client, admin_token, args.slot_id)
        suffix = str(time.time_ns())
        patients = [f"race-demo-{suffix}-{index}@example.com" for index in range(5)]
        await asyncio.gather(*(register_patient(client, email) for email in patients))
        tokens = await asyncio.gather(*(login(client, email, "secret123") for email in patients))
        print(f"\nStarting five concurrent bookings for slot {slot_id}...")
        results = await asyncio.gather(*(book(client, patient, token, slot_id) for patient, token in zip(patients, tokens)))

    print("\nConcurrent booking results")
    print("=" * 28)
    for index, result in enumerate(results, start=1):
        print(f"\nRequest {index}")
        print(f"  Patient: {result.patient}")
        print(f"  HTTP status: {result.status_code}")
        print(f"  Response: {result.body}")
    confirmed = [result for result in results if result.status_code == 202]
    conflicts = [result for result in results if result.status_code == 409]
    print(f"\nSummary: {len(confirmed)} confirmed, {len(conflicts)} conflict responses")
    if len(confirmed) != 1 or len(conflicts) != 4:
        raise SystemExit(f"FAILED: expected exactly one HTTP 202 and four HTTP 409 responses; got {len(confirmed)} and {len(conflicts)}")
    if confirmed[0].body.get("status") != "CONFIRMED":
        raise SystemExit(f"FAILED: winning appointment was not CONFIRMED: {confirmed[0].body}")
    print(f"PASS: slot {slot_id} produced exactly one CONFIRMED appointment.")


if __name__ == "__main__":
    asyncio.run(main())