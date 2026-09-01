from fastapi import APIRouter

from app.api.v1 import api_v1_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.search_enhanced import router as search_router
from app.api.v1.endpoints.assistant import router as assistant_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(api_v1_router, prefix="/api/v1")
api_router.include_router(search_router)
api_router.include_router(assistant_router)
