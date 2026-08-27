from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.settings import settings
from app.models import User
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import search_services

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse, summary="Search published services")
async def search_services_endpoint(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    results = await search_services(db, payload.query, min(payload.limit, settings.retrieval_top_k))
    return {
        "query": payload.query,
        "results": results,
        "message": "We don't offer a matching service." if not results else None,
    }