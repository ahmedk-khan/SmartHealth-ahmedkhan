import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.authorization import Permission, require_permission
from app.core.ai_controls import AIRedisStore, get_ai_redis_store
from app.core.dependencies import get_db
from app.models import User
from app.schemas.assistant import AssistantReportRequest
from app.services.communication_service import CommunicationService
from app.services.llm_provider import get_llm_provider
from app.workers.celery.reports import generate_utilisation_report_task

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate/utilisation")
async def generate_utilisation_report(
    payload: AssistantReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.ANALYTICS_READ)),
    ai_store: AIRedisStore = Depends(get_ai_redis_store),
):
    if not await ai_store.allow_request(current_user.id):
        from fastapi import HTTPException

        raise HTTPException(status_code=429, detail="AI request rate limit exceeded")

    async def events() -> AsyncIterator[str]:
        try:
            service = CommunicationService(db, get_llm_provider())
            result = await service.generate_utilisation_report(
                period_start=payload.period_start,
                period_end=payload.period_end,
                current_user=current_user,
            )
            report = result.report.model_dump(mode="json")
            metadata = result.metadata.model_dump(mode="json")
            for token in json.dumps(report, sort_keys=True).split():
                yield f"event: text\ndata: {json.dumps({'token': token + ' '})}\n\n"
            yield f"event: report\ndata: {json.dumps(report)}\n\n"
            yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
            yield f"event: citations\ndata: {json.dumps([{'source': 'analytics_daily', 'period_start': report['period_start'], 'period_end': report['period_end']}])}\n\n"
            yield f"event: done\ndata: {json.dumps({'report': report, 'metadata': metadata})}\n\n"
        except Exception:
            yield f"event: error\ndata: {json.dumps({'message': 'Report generation failed'})}\n\n"
            yield f"event: done\ndata: {json.dumps({'error': True})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post(
    "/generate/utilisation/async",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a utilisation report generation job",
    description="Starts a background Celery task for long-running utilisation report generation and returns a task ID for polling.",
)
async def queue_utilisation_report_job(
    payload: AssistantReportRequest,
    current_user: User = Depends(require_permission(Permission.ANALYTICS_READ)),
    ai_store: AIRedisStore = Depends(get_ai_redis_store),
):
    task = generate_utilisation_report_task.apply_async(
        args=[payload.period_start.isoformat(), payload.period_end.isoformat()],
        kwargs={"user_id": current_user.id},
    )
    if not await ai_store.set_task_owner(task.id, current_user.id):
        task.revoke(terminate=False)
        raise HTTPException(status_code=503, detail="Queued report ownership is unavailable")
    return {
        "task_id": task.id,
        "state": task.state,
        "status": "queued",
        "period_start": payload.period_start.isoformat(),
        "period_end": payload.period_end.isoformat(),
        "poll_url": f"/tasks/{task.id}",
    }
