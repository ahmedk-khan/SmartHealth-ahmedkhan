from fastapi import APIRouter

from app.api.v1 import api_v1_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.auth import router as auth_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(api_v1_router, prefix="/api/v1")
