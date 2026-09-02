"""
Enterprise Authorization Service - Simplified Pattern

Two-tier authorization model:
1. COARSE-GRAINED: Role-based permission mapping (role → permission)
2. FINE-GRAINED: Resource ownership/access guards (in endpoints)
"""

from app.models.user import User
from app.core.exceptions import ForbiddenError
from app.core.authorization.permissions import Permission, ROLE_PERMISSIONS


def check_permission(current_user: User, permission: Permission) -> None:
    """
    Coarse-grained permission check.
    
    Verifies user's role has the required permission.
    This is called at endpoint entry via require_permission() dependency.
    
    Raises ForbiddenError if permission is not granted.
    """
    user_permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    if permission not in user_permissions:
        raise ForbiddenError(
            detail=f"Permission denied: {current_user.role} lacks {permission}",
            error_type="forbidden"
        )
