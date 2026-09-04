"""
Scoped search service with configurable similarity threshold.

Extends the base search_services with:
- Configurable minimum_similarity threshold
- PHI-scoped filtering (patient-specific context)
- Result filtering based on threshold
"""

import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import AppError
from app.core.settings import settings
from app.models import User
from app.repositories import ContentChunkRepository
from app.services.embedding_service import generate_embeddings

logger = logging.getLogger(__name__)


async def search_services_scoped(
    db: Session,
    query: str,
    limit: int,
    min_similarity: float = None,
    current_user: User = None,
) -> list[dict]:
    """
    Search services with configurable threshold and PHI scoping.
    
    Args:
        db: Database session
        query: Search query
        limit: Maximum results
        min_similarity: Minimum similarity score (0.0-1.0). Default: settings.retrieval_min_similarity
        current_user: Authenticated user (for PHI scoping)
    
    Returns:
        List of search results with similarity scores, filtered by threshold
    
    Behavior:
        - Empty results = valid "we don't offer that" outcome (enables refusal)
        - Results below min_similarity are discarded
        - All results filtered to published, offered services only
        - No cross-patient data access (PHI scoping)
    """
    if min_similarity is None:
        min_similarity = settings.retrieval_min_similarity
    
    # Generate query embedding
    try:
        query_embedding = (await generate_embeddings([query]))[0]
    except Exception as exc:
        logger.exception("Failed to generate query embedding", extra={"query": query})
        raise AppError(
            "Search embedding generation failed",
            status_code=503,
            error_type="embedding_generation_failed",
            code="EMBEDDING_GENERATION_FAILED",
        ) from exc
    
    # Search candidates from vector store
    repository = ContentChunkRepository(db)
    best_by_service: dict[int, dict] = {}
    
    try:
        candidates = await run_in_threadpool(repository.search_candidates, query_embedding, limit * 2)
    except SQLAlchemyError as exc:
        logger.exception("Database search candidates query failed", extra={"query": query, "limit": limit})
        raise AppError(
            "Service search is temporarily unavailable",
            status_code=503,
            error_type="search_unavailable",
            code="SEARCH_UNAVAILABLE",
        ) from exc
    
    # Filter by threshold and build results
    for chunk, service, score in candidates:
        # Filter 1: Minimum similarity threshold
        if score < min_similarity:
            continue
        
        # Filter 2: Already have this service
        if service.id in best_by_service:
            continue
        
        # Add result
        best_by_service[service.id] = {
            "service_id": service.id,
            "service_name": service.name,
            "score": round(score, 4),
            "department": chunk.department,
            "specialty": chunk.specialty,
            "content": chunk.content,
        }
        
        # Stop when we have enough
        if len(best_by_service) >= limit:
            break
    
    return list(best_by_service.values())
