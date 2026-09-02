"""
SmartHealth Authorization Module - Simplified Enterprise Pattern

Two-tier authorization:
1. COARSE-GRAINED: require_permission() - role-based permission checks
2. FINE-GRAINED: Guard classes - resource ownership/access checks
"""

from app.core.authorization.permissions import Permission
from app.core.dependencies import (
    require_permission,
    require_admin,
    require_staff,
    require_admin_or_front_desk,
    require_patient,
    require_provider,
)
from app.core.authorization.policies import (
    PatientOwnershipGuard,
    ProviderOwnershipGuard,
    SlotOwnershipGuard,
    ServiceOwnershipGuard,
    AppointmentOwnershipGuard,
    VisitTransitionGuard,
    NoShowGuard,
)

__all__ = [
    # Permissions
    "Permission",
    # Dependencies (role-based & permission-based)
    "require_permission",
    "require_admin",
    "require_staff",
    "require_admin_or_front_desk",
    "require_patient",
    "require_provider",
    # Guards (resource-based)
    "PatientOwnershipGuard",
    "ProviderOwnershipGuard",
    "SlotOwnershipGuard",
    "ServiceOwnershipGuard",
    "AppointmentOwnershipGuard",
    "VisitTransitionGuard",
    "NoShowGuard",
]
