"""
Enhanced search endpoint with configurable thresholds and PHI scoping.

Features:
- Semantic search over published, offered services
- Configurable k and minimum similarity threshold
- Patient-specific context with PHI scoping
- Empty result as valid "we don't offer" outcome
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
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
    min_similarity: float = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold (0.0-1.0). Results below this are discarded. Default from settings.",
    ),
):
    """
    Search published services.
    
    Args:
        payload: SearchRequest with query and limit
        db: Database session
        current_user: Authenticated user (for PHI scoping)
        min_similarity: Optional override for minimum similarity threshold
    
    Returns:
        SearchResponse with results and optional patient context
    """
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
        patient_context = get_patient_context(db, current_user)
    
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


@router.get(
    "/search/config",
    summary="Get current search configuration",
    description="Returns current search configuration (k, min_similarity, etc.)",
)
async def get_search_config():
    """Return current search configuration."""
    return {
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_min_similarity": settings.retrieval_min_similarity,
        "embedding_dimensions": settings.embedding_dimensions,
        "embedding_model": settings.embedding_model,
    }
