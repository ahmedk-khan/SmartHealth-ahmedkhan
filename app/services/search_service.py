import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import AppError
from app.core.settings import settings
from app.repositories import ContentChunkRepository
from app.services.embedding_service import generate_embeddings

logger = logging.getLogger(__name__)


async def search_services(db: Session, query: str, limit: int) -> list[dict]:
    query_embedding = (await generate_embeddings([query]))[0]
    repository = ContentChunkRepository(db)
    best_by_service: dict[int, dict] = {}
    try:
        candidates = await run_in_threadpool(repository.search_candidates, query_embedding, limit)
    except SQLAlchemyError as exc:
        logger.exception("Database search candidates query failed", extra={"query": query, "limit": limit})
        raise AppError(
            "Service search is temporarily unavailable",
            status_code=503,
            error_type="search_unavailable",
            code="SEARCH_UNAVAILABLE",
        ) from exc

    for chunk, service, score in candidates:
        if score < settings.retrieval_min_similarity or service.id in best_by_service:
            continue
        best_by_service[service.id] = {
            "service_id": service.id,
            "service_name": service.name,
            "score": round(score, 4),
            "department": chunk.department,
            "specialty": chunk.specialty,
            "content": chunk.content,
        }
        if len(best_by_service) >= limit:
            break
    return list(best_by_service.values())
