from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppError
from app.core.settings import settings
from app.repositories import ContentChunkRepository
from app.services.embedding_service import generate_embeddings


async def search_services(db: Session, query: str, limit: int) -> list[dict]:
    query_embedding = (await generate_embeddings([query]))[0]
    repository = ContentChunkRepository(db)
    best_by_service: dict[int, dict] = {}
    try:
        candidates = repository.search_candidates(query_embedding, limit)
    except SQLAlchemyError as exc:
        raise AppError(
            "Service search is temporarily unavailable",
            status_code=503,
            error_type="search_unavailable",
            detail=str(exc),
        ) from exc

    for chunk, service, score in candidates:
        if score < settings.retrieval_min_similarity or service.id in best_by_service:
            continue
        best_by_service[service.id] = {
            "service_id": service.id,
            "service_name": service.name,
            "score": round(score, 4),
            "department": service.department.name,
            "specialty": service.specialty,
            "content": chunk.content,
        }
        if len(best_by_service) >= limit:
            break
    return list(best_by_service.values())