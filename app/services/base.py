import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_correlation_id, get_request_id


logger = logging.getLogger(__name__)


class BaseService:
    """
    Base service class with built-in structured logging support.
    
    Automatically includes correlation ID and request ID in all log messages,
    ensuring full traceability across the application.
    """
    
    def __init__(self, db: Session) -> None:
        self.db = db
    
    def _log_operation(
        self,
        level: str,
        message: str,
        operation: str = "",
        data: Optional[dict[str, Any]] = None,
        exc_info: bool = False,
    ) -> None:
        """
        Log an operation with structured context including correlation ID.
        
        Args:
            level: Logging level ('info', 'warning', 'error', 'debug')
            message: Log message
            operation: Operation name for context
            data: Additional data to include in logs (PHI will be sanitized)
            exc_info: Whether to include exception info
        """
        log_data = {
            "operation": operation,
            "correlation_id": get_correlation_id(),
            "request_id": get_request_id(),
            **(data or {})
        }
        
        log_method = getattr(logger, level)
        log_method(message, extra=log_data, exc_info=exc_info)
    
    def log_info(self, message: str, operation: str = "", data: Optional[dict[str, Any]] = None) -> None:
        """Log info message with structured context."""
        self._log_operation("info", message, operation, data)
    
    def log_warning(self, message: str, operation: str = "", data: Optional[dict[str, Any]] = None) -> None:
        """Log warning message with structured context."""
        self._log_operation("warning", message, operation, data)
    
    def log_error(self, message: str, operation: str = "", data: Optional[dict[str, Any]] = None, exc_info: bool = False) -> None:
        """Log error message with structured context."""
        self._log_operation("error", message, operation, data, exc_info)
    
    def log_debug(self, message: str, operation: str = "", data: Optional[dict[str, Any]] = None) -> None:
        """Log debug message with structured context."""
        self._log_operation("debug", message, operation, data)