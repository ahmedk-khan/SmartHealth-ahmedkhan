from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api import api_router
from app.core.exceptions import AppError, app_error_handler, generate_request_id, http_exception_handler, unexpected_exception_handler, validation_exception_handler
from app.core.logging import set_correlation_id, set_request_id, reset_correlation_id, reset_request_id, get_correlation_id, configure_logging
from app.db import init_db


logger = logging.getLogger(__name__)

# Configure structured JSON logging
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="SmartHealth", lifespan=lifespan)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to extract/generate correlation ID and request ID, and set them in context variables."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate correlation ID (should persist across a user/workflow)
        correlation_id = request.headers.get("X-Correlation-ID") or generate_request_id()
        
        # Extract or generate request ID (specific to this HTTP request)
        request_id = request.headers.get("X-Request-ID") or generate_request_id()
        
        # Store in request state for access in route handlers
        request.state.correlation_id = correlation_id
        request.state.request_id = request_id
        
        # Set context variables for logging and downstream tasks
        correlation_token = set_correlation_id(correlation_id)
        request_token = set_request_id(request_id)
        
        try:
            response = await call_next(request)
        finally:
            # Clean up context variables
            reset_correlation_id(correlation_token)
            reset_request_id(request_token)
        
        # Add correlation ID and request ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(CorrelationIdMiddleware)


app.exception_handler(AppError)(app_error_handler)
app.exception_handler(RequestValidationError)(validation_exception_handler)
app.exception_handler(HTTPException)(http_exception_handler)
app.exception_handler(Exception)(unexpected_exception_handler)


@app.get("/")
def root():
    return {"message": "app api is running"}


app.include_router(api_router)
