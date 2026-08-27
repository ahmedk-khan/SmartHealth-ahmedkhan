from celery.result import AsyncResult
from fastapi import APIRouter, Depends

from app.celery_app import celery_app
from app.core.dependencies import get_current_user
from app.core.exceptions import AppError
from app.models import User

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get(
    "/{task_id}",
    summary="Get task status",
    description="Checks the status of a background Celery task and returns its final or in-progress result when available.",
)
def get_task_status(task_id: str, current_user: User = Depends(get_current_user)) -> dict[str, object]:
    if current_user.role.value not in {"admin", "front_desk"}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    result = AsyncResult(task_id, app=celery_app)
    response: dict[str, object] = {"task_id": task_id, "state": result.state}
    if result.ready():
        payload = result.result
        if isinstance(payload, (str, int, float, bool, list, dict)) or payload is None:
            response["result"] = payload
        else:
            response["result"] = str(payload)
    return response

