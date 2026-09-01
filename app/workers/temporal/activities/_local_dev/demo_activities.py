"""Development-only activities.

This file is intentionally outside the production activity registration path.
It may contain demo timing behavior, but production activities must remain
thin service adapters with no direct I/O or business logic.
"""

import asyncio
from typing import Any

from temporalio import activity


@activity.defn
async def wait_for_worker_interruption(appointment_data: dict[str, Any]) -> dict[str, bool]:
    """Keep a demo booking pending until its worker is interrupted."""
    if activity.info().attempt > 1:
        return {"worker_restarted": True}
    while True:
        activity.heartbeat(appointment_data.get("slot_id"))
        await asyncio.sleep(1)
