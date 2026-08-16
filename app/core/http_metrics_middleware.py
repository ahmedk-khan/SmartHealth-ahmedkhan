"""
HTTP metrics middleware for Prometheus tracking.

Tracks request latency, response size, HTTP status codes, and exceptions
with proper exception handling to avoid breaking request processing.
"""

import logging
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.metrics import record_http_request, record_http_exception


logger = logging.getLogger(__name__)


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to record HTTP metrics for Prometheus.
    
    Tracks:
    - Request count by method, endpoint, and status
    - Request latency by method and endpoint
    - Response size by method and endpoint
    - Exceptions by type and endpoint
    """
    
    def __init__(self, app, skip_paths: list[str] | None = None):
        """
        Initialize metrics middleware.
        
        Args:
            app: FastAPI application
            skip_paths: List of paths to skip metrics recording (e.g., ['/health', '/metrics'])
        """
        super().__init__(app)
        self.skip_paths = skip_paths or []
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and record metrics.
        
        Args:
            request: HTTP request
            call_next: Next middleware/route handler
        
        Returns:
            HTTP response with metrics recorded
        """
        # Skip metrics recording for certain paths
        if self._should_skip(request.url.path):
            return await call_next(request)
        
        # Extract request info
        method = request.method
        endpoint = self._normalize_endpoint(request.url.path)
        
        # Record request start time
        start_time = time.time()
        
        try:
            # Call next handler
            response = await call_next(request)
            
            # Calculate metrics
            duration_seconds = time.time() - start_time
            status_code = response.status_code
            response_size_bytes = self._get_response_size(response)
            
            # Record HTTP metrics
            try:
                record_http_request(
                    method=method,
                    endpoint=endpoint,
                    status=status_code,
                    duration_seconds=duration_seconds,
                    response_size_bytes=response_size_bytes,
                )
            except Exception as exc:
                logger.error(f"Failed to record HTTP metrics: {exc}", exc_info=True)
            
            return response
        
        except Exception as exc:
            # Record exception metrics
            exception_type = type(exc).__name__
            try:
                record_http_exception(
                    exception_type=exception_type,
                    endpoint=endpoint,
                )
            except Exception as metric_exc:
                logger.error(f"Failed to record exception metric: {metric_exc}", exc_info=True)
            
            # Re-raise exception for error handlers
            raise
    
    @staticmethod
    def _should_skip(path: str) -> bool:
        """
        Check if path should be skipped from metrics.
        
        Args:
            path: Request path
        
        Returns:
            True if path should be skipped
        """
        skip_paths = ["/health", "/metrics", "/docs", "/openapi.json", "/redoc"]
        return any(path.startswith(skip_path) for skip_path in skip_paths)
    
    @staticmethod
    def _normalize_endpoint(path: str) -> str:
        """
        Normalize endpoint path for metrics labeling.
        
        Converts dynamic paths like /appointments/123 to /appointments/{id}
        to avoid high cardinality labels.
        
        Args:
            path: Request path
        
        Returns:
            Normalized endpoint path
        """
        import re
        
        # Replace numeric IDs with placeholders
        normalized = re.sub(r"/\d+", "/{id}", path)
        
        # Remove query parameters
        normalized = normalized.split("?")[0]
        
        return normalized or "/"
    
    @staticmethod
    def _get_response_size(response: Response) -> int:
        """
        Get response size in bytes.
        
        Args:
            response: HTTP response
        
        Returns:
            Response size in bytes
        """
        try:
            if hasattr(response, "body"):
                return len(response.body)
            
            # For streaming responses
            if hasattr(response, "media_type"):
                # Estimate based on content-length header if available
                if hasattr(response, "headers") and "content-length" in response.headers:
                    return int(response.headers["content-length"])
        
            return 0
        except Exception as exc:
            logger.debug(f"Could not determine response size: {exc}")
            return 0
