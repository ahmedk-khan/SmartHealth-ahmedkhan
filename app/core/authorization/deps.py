"""FastAPI authorization dependencies.

Coarse-grained access control lives here. Fine-grained resource checks use
guard classes from ``policies`` inside service methods.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from fastapi import Depends

from app.core.authorization.permissions import Permission
from app.core.authorization.service import check_permission
from app.core.dependencies import get_current_user
from app.core.exceptions import ForbiddenError
from app.models import User, UserRole


def _role_value(role: str | UserRole | Enum) -> str:
    if isinstance(role, UserRole):
        return role.value
    if isinstance(role, Enum):
        return str(role.value)
    return str(role)


def require_role(*roles: str | UserRole | Enum) -> Callable[..., User]:
    """Require the authenticated user to have one of the given roles."""
    allowed = {_role_value(role) for role in roles}

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in allowed:
            raise ForbiddenError(
                message="Role access denied",
                code="ROLE_ACCESS_DENIED",
                detail={"required_roles": sorted(allowed), "actual_role": current_user.role.value},
            )
        return current_user

    return dependency


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise ForbiddenError(
            message="Admin access required",
            code="ROLE_ACCESS_DENIED",
            detail={"required_roles": ["admin"], "actual_role": current_user.role.value},
        )
    return current_user


def require_admin_or_front_desk(
    current_user: User = Depends(require_role(UserRole.admin, UserRole.front_desk)),
) -> User:
    return current_user


def require_permission(permission: Permission) -> Callable[..., User]:
    """Require a coarse-grained permission granted by the user's role."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        check_permission(current_user, permission)
        return current_user

    dependency.__required_permission__ = permission.value
    return dependency
