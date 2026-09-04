"""Coarse-grained authorization service functions."""

from app.core.authorization.permissions import Permission, ROLE_PERMISSIONS
from app.core.exceptions import AccessDeniedError, PermissionDeniedError
from app.models.user import User, UserRole


def check_permission(current_user: User, permission: Permission) -> None:
    """Verify the user's role includes the required permission."""
    user_permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    if permission not in user_permissions:
        raise PermissionDeniedError(
            message="Permission denied",
            detail=f"{current_user.role.value} lacks {permission.value}",
        )


def ensure_admin_or_front_desk(current_user: User) -> None:
    """Backward-compatible staff check for communication generation paths."""
    if current_user.role not in {UserRole.admin, UserRole.front_desk}:
        raise AccessDeniedError(
            message="Admin or front desk access required",
            detail={"required_roles": ["admin", "front_desk"], "actual_role": current_user.role.value},
        )
