from typing import Any
from app.models.user import User
from app.core.exceptions import ForbiddenError
from app.core.authorization.permissions import Permission, ROLE_PERMISSIONS
from app.core.authorization.policies import (
    PatientPolicy,
    ProviderPolicy,
    SlotPolicy,
    ServicePolicy,
    AppointmentPolicy,
)

def authorize(
    current_user: User,
    permission: Permission,
    resource: Any = None,
    **kwargs: Any,
) -> None:
    # 1. Coarse-grained permission check (role-to-permission mapping)
    user_permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    if permission not in user_permissions:
        raise ForbiddenError(f"User lacks required permission: {permission}")

    # If no resource is provided, coarse-grained permission check is sufficient
    if resource is None:
        return

    # 2. Resource-level policy check
    is_authorized = False

    # Patient Policy checks
    if permission in {Permission.PATIENT_READ, Permission.PATIENT_UPDATE, Permission.PATIENT_DELETE}:
        if permission == Permission.PATIENT_READ:
            is_authorized = PatientPolicy.can_read(current_user, resource)
        elif permission == Permission.PATIENT_UPDATE:
            is_authorized = PatientPolicy.can_update(current_user, resource)
        else:
            is_authorized = PatientPolicy.can_delete(current_user, resource)

    # Provider Policy checks
    elif permission == Permission.PROVIDER_UPDATE:
        is_authorized = ProviderPolicy.can_update(current_user, resource)
    elif permission in {Permission.SLOT_READ, Permission.SERVICE_READ} and resource.__class__.__name__ == "Provider":
        is_authorized = ProviderPolicy.can_access_records(current_user, resource, kwargs.get("provider_repository"))

    # Slot Policy checks
    elif permission == Permission.SLOT_CREATE:
        # Resource is provider_id
        is_authorized = SlotPolicy.can_create(current_user, resource, kwargs.get("provider_repository"))
    elif permission in {Permission.SLOT_UPDATE, Permission.SLOT_DELETE}:
        if permission == Permission.SLOT_UPDATE:
            is_authorized = SlotPolicy.can_update(current_user, resource, kwargs.get("provider_repository"))
        else:
            is_authorized = SlotPolicy.can_delete(current_user, resource, kwargs.get("provider_repository"))

    # Service Policy checks
    elif permission in {Permission.SERVICE_UPDATE, Permission.SERVICE_PUBLISH, Permission.SERVICE_UNPUBLISH}:
        if permission == Permission.SERVICE_UPDATE:
            is_authorized = ServicePolicy.can_update(current_user, resource, kwargs.get("provider_repository"))
        elif permission == Permission.SERVICE_PUBLISH:
            if "stage" in kwargs and kwargs["stage"] == "status":
                is_authorized = ServicePolicy.can_access_status(current_user, resource, kwargs.get("provider_repository"))
            else:
                is_authorized = ServicePolicy.can_publish(current_user, resource, kwargs.get("provider_repository"))
        else:
            is_authorized = ServicePolicy.can_unpublish(current_user, resource, kwargs.get("provider_repository"))

    # Appointment Policy checks
    elif permission in {Permission.APPOINTMENT_READ, Permission.APPOINTMENT_CANCEL, Permission.APPOINTMENT_UPDATE, Permission.BILLING_CREATE, Permission.VISIT_UPDATE}:
        if "target_status" in kwargs:
            is_authorized = AppointmentPolicy.can_transition_visit(
                current_user,
                resource,
                kwargs["target_status"],
                kwargs.get("provider_repository"),
            )
        elif permission == Permission.APPOINTMENT_UPDATE and kwargs.get("is_no_show"):
            is_authorized = AppointmentPolicy.can_mark_no_show(current_user, resource, kwargs.get("provider_repository"))
        elif permission == Permission.APPOINTMENT_CANCEL:
            is_authorized = AppointmentPolicy.can_cancel(
                current_user,
                resource,
                kwargs.get("patient_repository"),
                kwargs.get("provider_repository"),
            )
        elif permission == Permission.APPOINTMENT_UPDATE:
            is_authorized = AppointmentPolicy.can_reschedule(
                current_user,
                resource,
                kwargs.get("patient_repository"),
                kwargs.get("provider_repository"),
            )
        elif permission == Permission.BILLING_CREATE:
            is_authorized = AppointmentPolicy.can_billing_precheck(
                current_user,
                resource,
                kwargs.get("patient_repository"),
                kwargs.get("provider_repository"),
            )
        else:
            is_authorized = AppointmentPolicy.can_read(
                current_user,
                resource,
                kwargs.get("patient_repository"),
                kwargs.get("provider_repository"),
            )

    if not is_authorized:
        raise ForbiddenError(f"Access to resource denied for permission: {permission}")
