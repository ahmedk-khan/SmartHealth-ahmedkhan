"""
SmartHealth authorization package.

Two-tier model:
1. Coarse-grained RBAC via ``Permission`` + ``require_permission`` dependencies
2. Fine-grained resource checks via guard classes in ``policies``
"""

from app.core.authorization.deps import (
    require_admin,
    require_admin_or_front_desk,
    require_permission,
    require_role,
)
from app.core.authorization.permissions import Permission
from app.core.authorization.policies import (
    AppointmentOwnershipGuard,
    NoShowGuard,
    PatientOwnershipGuard,
    ProviderOwnershipGuard,
    ServiceOwnershipGuard,
    SlotOwnershipGuard,
    VisitTransitionGuard,
)
from app.core.authorization.service import check_permission, ensure_admin_or_front_desk

__all__ = [
    "Permission",
    "check_permission",
    "ensure_admin_or_front_desk",
    "require_permission",
    "require_role",
    "require_admin",
    "require_admin_or_front_desk",
    "PatientOwnershipGuard",
    "ProviderOwnershipGuard",
    "SlotOwnershipGuard",
    "ServiceOwnershipGuard",
    "AppointmentOwnershipGuard",
    "VisitTransitionGuard",
    "NoShowGuard",
]
