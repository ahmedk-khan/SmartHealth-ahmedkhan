from app.core.authorization.permissions import Permission
from app.core.authorization.service import authorize
from app.core.authorization.dependencies import require_permission

__all__ = ["Permission", "authorize", "require_permission"]
