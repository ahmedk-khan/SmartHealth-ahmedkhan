from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api import api_router
from app.core.exceptions import AppError, app_error_handler, generate_request_id, http_exception_handler, unexpected_exception_handler, validation_exception_handler
from app.db import init_db


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="SmartHealth", lifespan=lifespan)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or generate_request_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIdMiddleware)


app.exception_handler(AppError)(app_error_handler)
app.exception_handler(RequestValidationError)(validation_exception_handler)
app.exception_handler(HTTPException)(http_exception_handler)
app.exception_handler(Exception)(unexpected_exception_handler)


@app.get("/")
def root():
    return {"message": "app api is running"}


app.include_router(api_router)
