import asyncio
import httpx

BASE_URL = "http://localhost:8000"
SLOT_ID = 123
TOKEN = "paste_patient_token_here"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

async def book(client, i):
    r = await client.post(
        f"{BASE_URL}/api/v1/appointments",
        headers=headers,
        json={"slot_id": SLOT_ID},
    )
    return i, r.status_code, r.text

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        results = await asyncio.gather(*[book(client, i) for i in range(5)])
    for result in results:
        print(result)

asyncio.run(main())