from fastapi import APIRouter

from app.api.v1.endpoints.departments import router as departments_router
from app.api.v1.endpoints.patients import router as patients_router
from app.api.v1.endpoints.providers import router as providers_router
from app.api.v1.endpoints.public import router as public_router
from app.api.v1.endpoints.services import router as services_router
from app.api.v1.endpoints.slots import router as slots_router

api_v1_router = APIRouter()
api_v1_router.include_router(departments_router)
api_v1_router.include_router(patients_router)
api_v1_router.include_router(providers_router)
api_v1_router.include_router(public_router)
api_v1_router.include_router(services_router)
api_v1_router.include_router(slots_router)
