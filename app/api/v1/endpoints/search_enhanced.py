"""
Enhanced search endpoint with configurable thresholds and PHI scoping.

Returns a JSON payload (not SSE) because semantic search is a single retrieval
operation rather than a generative token stream.
"""

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_ai_rate_limit
from app.core.authorization import Permission, require_permission
from app.core.settings import settings
from app.models import User, UserRole
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_services_scoped import search_services_scoped
from app.services.patient_context_service import get_patient_context

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
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
    current_user: User = Depends(require_permission(Permission.AI_SEARCH_USE)),
    _: User = Depends(require_ai_rate_limit),
    min_similarity: float = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold (0.0-1.0). Results below this are discarded. Default from settings.",
    ),
):
    threshold = min_similarity if min_similarity is not None else settings.retrieval_min_similarity
    limit = min(payload.limit, settings.retrieval_top_k)

    results = await search_services_scoped(
        db,
        query=payload.query,
        limit=limit,
        min_similarity=threshold,
        current_user=current_user,
    )

    patient_context = None
    if current_user.role == UserRole.patient:
        patient_context = await asyncio.to_thread(get_patient_context, db, current_user)

    return SearchResponse(
        query=payload.query,
        results=results,
        min_similarity_used=round(threshold, 4),
        results_count=len(results),
        message="We don't offer a matching service." if not results else None,
        patient_context=patient_context,
    )
