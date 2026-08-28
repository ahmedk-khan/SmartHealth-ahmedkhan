from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import generate_request_id, reset_correlation_id, reset_request_id, set_correlation_id, set_request_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach correlation and request identifiers to each HTTP request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or generate_request_id()
        request_id = request.headers.get("X-Request-ID") or generate_request_id()

        request.state.correlation_id = correlation_id
        request.state.request_id = request_id

        correlation_token = set_correlation_id(correlation_id)
        request_token = set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(correlation_token)
            reset_request_id(request_token)

        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Request-ID"] = request_id
        return response
