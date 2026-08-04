from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api import api_router
from app.core.exceptions import AppError, format_app_error
from app.db import init_db

app = FastAPI(title="SmartHealth")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.exception_handler(AppError)
def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=format_app_error(exc))


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "validation_error", "message": "Request validation failed", "detail": exc.errors()}},
    )


@app.exception_handler(PermissionError)
def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": {"type": "forbidden", "message": str(exc), "detail": None}})


@app.exception_handler(ValueError)
def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": {"type": "value_error", "message": str(exc), "detail": None}})


@app.get("/")
def root():
    return {"message": "app api is running"}


app.include_router(api_router)
