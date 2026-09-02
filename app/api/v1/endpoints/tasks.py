from celery.result import AsyncResult
from fastapi import APIRouter, Depends
from fastapi import HTTPException

from app.workers.celery_app import celery_app
from app.core.authorization import require_permission, Permission
from app.models import User
from app.core.ai_controls import AIRedisStore, get_ai_redis_store

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get(
    "/{task_id}",
    summary="Get task status",
    description="Checks the status of a background Celery task and returns its final or in-progress result when available.",
)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(require_permission(Permission.TASK_READ)),
    ai_store: AIRedisStore = Depends(get_ai_redis_store),
) -> dict[str, object]:
    owner_id = await ai_store.get_task_owner(task_id)
    if owner_id is None or owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    result = AsyncResult(task_id, app=celery_app)
    response: dict[str, object] = {"task_id": task_id, "state": result.state}
    if result.ready():
        payload = result.result
        if isinstance(payload, (str, int, float, bool, list, dict)) or payload is None:
            response["result"] = payload
        else:
            response["result"] = str(payload)
    return response
