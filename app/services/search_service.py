import logging
import re

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import AppError
from app.core.settings import settings
from app.repositories import ContentChunkRepository
from app.models import Department, Service, ServiceStatus
from app.services.embedding_service import generate_embeddings

logger = logging.getLogger(__name__)


def _provider_names(service: Service) -> list[str]:
    names = []
    for provider in service.providers:
        user = provider.user
        name = " ".join(part for part in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if part).strip()
        names.append(name or getattr(provider, "specialty", None) or "Clinic provider")
    return names


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
            "price": service.price,
            "providers": _provider_names(service),
        }
        if len(best_by_service) >= limit:
            break

    if not best_by_service:
        # Fake embeddings and low-confidence queries still need an obvious catalog match.
        stop_words = {"what", "which", "service", "services", "offer", "offers", "related", "to", "the", "for", "any", "slots", "available"}
        terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2 and term not in stop_words]
        if terms:
            def find_catalog_matches() -> list[dict]:
                services = db.query(Service).join(Department).filter(
                    Service.status == ServiceStatus.PUBLISHED,
                    Service.is_published.is_(True),
                ).filter(
                    or_(*(
                        field.ilike(f"%{term}%")
                        for term in terms
                        for field in (Service.name, Service.description, Service.specialty, Department.name)
                    ))
                ).order_by(Service.id).limit(limit).all()
                return [
                    {
                        "service_id": service.id,
                        "service_name": service.name,
                        "score": 1.0,
                        "department": service.department.name if service.department else "General",
                        "specialty": service.specialty,
                        "content": service.description or "",
                        "price": service.price,
                        "providers": _provider_names(service),
                    }
                    for service in services
                ]

            for result in await run_in_threadpool(find_catalog_matches):
                best_by_service[result["service_id"]] = result
    return list(best_by_service.values())
