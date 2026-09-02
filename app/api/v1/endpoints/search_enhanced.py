"""
Enhanced search endpoint with configurable thresholds and PHI scoping.

Features:
- Semantic search over published, offered services
- Configurable k and minimum similarity threshold
- Patient-specific context with PHI scoping
- Empty result as valid "we don't offer" outcome
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.ai_controls import AIRedisStore, get_ai_redis_store
from app.core.settings import settings
from app.models import User, UserRole
from app.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.services.search_services_scoped import search_services_scoped
from app.services.patient_context_service import get_patient_context

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    summary="Semantic search over published services",
    description="""
    Search the clinic's published services using semantic similarity.
    
    - Query is converted to embedding and matched against service descriptions
    - Results filtered to published, offered services only
    - Patient-specific context (e.g., their appointments) scoped to authenticated patient
    - Empty results mean clinic doesn't offer that service (valid refusal outcome)
    """,
)
async def search_services_endpoint(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    ai_store: AIRedisStore = Depends(get_ai_redis_store),
    min_similarity: float = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold (0.0-1.0). Results below this are discarded. Default from settings.",
    ),
):
    """Search published services and stream grounded results."""
    if not await ai_store.allow_request(current_user.id):
        raise HTTPException(status_code=429, detail="AI request rate limit exceeded")
    # Use provided threshold or default from settings
    threshold = min_similarity if min_similarity is not None else settings.retrieval_min_similarity
    limit = min(payload.limit, settings.retrieval_top_k)
    
    # Perform scoped search
    results = await search_services_scoped(
        db,
        query=payload.query,
        limit=limit,
        min_similarity=threshold,
        current_user=current_user,
    )
    
    # Get patient context (if authenticated as patient)
    patient_context = None
    if current_user.role == UserRole.patient:
        patient_context = await asyncio.to_thread(get_patient_context, db, current_user)
    
    response = {
        "query": payload.query,
        "results": results,
        "min_similarity_used": round(threshold, 4),
        "results_count": len(results),
        "message": "We don't offer a matching service." if not results else None,
        "patient_context": patient_context,
    }

    async def events() -> AsyncIterator[str]:
        for result in results:
            yield f"event: result\ndata: {json.dumps(result)}\n\n"
        metadata = {key: value for key, value in response.items() if key != "results"}
        yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
        yield f"event: done\ndata: {json.dumps(response)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


