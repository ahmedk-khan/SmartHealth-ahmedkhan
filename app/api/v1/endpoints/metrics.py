"""
Prometheus metrics endpoints.

Provides `/metrics` endpoint for Prometheus scraping in standard format.
"""

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from starlette.responses import Response


def create_metrics_endpoint():
    """
    Create metrics endpoint handler.
    
    Returns:
        Callable that returns Prometheus metrics in text format
    """
    
    async def metrics() -> Response:
        """
        Generate Prometheus metrics in text/plain format.
        
        This endpoint is scraped by Prometheus to collect all metrics
        including HTTP metrics and domain counters.
        
        Returns:
            Response with Prometheus metrics in text format
        """
        try:
            metrics_data = generate_latest(REGISTRY)
            return Response(
                content=metrics_data,
                media_type=CONTENT_TYPE_LATEST,
            )
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to generate metrics: {exc}", exc_info=True)
            
            # Return empty metrics on error to avoid breaking scraping
            return Response(
                content=b"# Error generating metrics\n",
                media_type="text/plain; charset=utf-8",
                status_code=500,
            )
    
    return metrics
