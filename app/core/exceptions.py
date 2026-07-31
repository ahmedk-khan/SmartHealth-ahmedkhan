from typing import Any


class AppError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_type: str = "app_error",
        detail: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.detail = detail


def format_app_error(exc: AppError) -> dict:
    return {
        "error": {
            "type": exc.error_type,
            "message": exc.message,
            "detail": exc.detail,
        }
    }
