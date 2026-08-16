from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/health",
    tags=["health"],
    summary="Health check",
    description="Confirms that the application is running and ready to serve requests.",
)
def health():
    return {"status": "ok"}
