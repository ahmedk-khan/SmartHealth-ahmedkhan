from celery.result import AsyncResult
from fastapi import APIRouter, Query

from app.celery_app import celery_app
from app.tasks import trivial_ping

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/ping", status_code=202)
def enqueue_ping(message: str = Query(default="pong")) -> dict[str, str]:
    task = trivial_ping.delay(message)
    return {"task_id": task.id, "state": task.state}


@router.get("/{task_id}")
def get_task_status(task_id: str) -> dict[str, object]:
    result = AsyncResult(task_id, app=celery_app)
    response: dict[str, object] = {"task_id": task_id, "state": result.state}
    if result.ready():
        payload = result.result
        if isinstance(payload, (str, int, float, bool, list, dict)) or payload is None:
            response["result"] = payload
        else:
            response["result"] = str(payload)
    return response
