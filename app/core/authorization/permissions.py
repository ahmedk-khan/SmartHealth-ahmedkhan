from enum import Enum
from app.models.user import UserRole

class Permission(str, Enum):
    # Analytics
    ANALYTICS_READ = "analytics:read"
    ANALYTICS_RECONCILE = "analytics:reconcile"

    # Departments
    DEPARTMENT_CREATE = "department:create"
    DEPARTMENT_READ = "department:read"

    # Tasks
    TASK_READ = "task:read"

    # Patients
    PATIENT_READ = "patient:read"
    PATIENT_UPDATE = "patient:update"
    PATIENT_DELETE = "patient:delete"

    # Providers
    PROVIDER_CREATE = "provider:create"
    PROVIDER_READ = "provider:read"
    PROVIDER_UPDATE = "provider:update"

    # Slots
    SLOT_CREATE = "slot:create"
    SLOT_READ = "slot:read"
    SLOT_UPDATE = "slot:update"
    SLOT_DELETE = "slot:delete"
    SLOT_RESERVE = "slot:reserve"

    # Services
    SERVICE_CREATE = "service:create"
    SERVICE_READ = "service:read"
    SERVICE_UPDATE = "service:update"
    SERVICE_PUBLISH = "service:publish"
    SERVICE_UNPUBLISH = "service:unpublish"

    # Appointments
    APPOINTMENT_CREATE = "appointment:create"
    APPOINTMENT_READ = "appointment:read"
    APPOINTMENT_CANCEL = "appointment:cancel"
    APPOINTMENT_UPDATE = "appointment:update"
    WAITLIST_JOIN = "waitlist:join"

    # Visits
    VISIT_UPDATE = "visit:update"

    # Billing
    BILLING_CREATE = "billing:create"

    # Notifications
    NOTIFICATION_READ = "notification:read"


ROLE_PERMISSIONS = {
    UserRole.admin: {p for p in Permission},
    UserRole.front_desk: {
        Permission.ANALYTICS_READ,
        Permission.ANALYTICS_RECONCILE,
        Permission.DEPARTMENT_CREATE,
        Permission.DEPARTMENT_READ,
        Permission.TASK_READ,
        Permission.PATIENT_READ,
        Permission.PATIENT_UPDATE,
        Permission.PATIENT_DELETE,
        Permission.PROVIDER_CREATE,
        Permission.PROVIDER_READ,
        Permission.PROVIDER_UPDATE,
        Permission.SLOT_CREATE,
        Permission.SLOT_READ,
        Permission.SLOT_UPDATE,
        Permission.SLOT_DELETE,
        Permission.SERVICE_CREATE,
        Permission.SERVICE_READ,
        Permission.SERVICE_UPDATE,
        Permission.SERVICE_PUBLISH,
        Permission.SERVICE_UNPUBLISH,
        Permission.APPOINTMENT_READ,
        Permission.APPOINTMENT_CANCEL,
        Permission.APPOINTMENT_UPDATE,
        Permission.VISIT_UPDATE,
        Permission.BILLING_CREATE,
        Permission.NOTIFICATION_READ,
    },
    UserRole.provider: {
        Permission.DEPARTMENT_READ,
        Permission.PATIENT_READ,
        Permission.PROVIDER_CREATE,
        Permission.PROVIDER_READ,
        Permission.PROVIDER_UPDATE,
        Permission.SLOT_CREATE,
        Permission.SLOT_READ,
        Permission.SLOT_UPDATE,
        Permission.SLOT_DELETE,
        Permission.SERVICE_CREATE,
        Permission.SERVICE_READ,
        Permission.SERVICE_UPDATE,
        Permission.SERVICE_PUBLISH,
        Permission.SERVICE_UNPUBLISH,
        Permission.APPOINTMENT_READ,
        Permission.APPOINTMENT_CANCEL,
        Permission.APPOINTMENT_UPDATE,
        Permission.VISIT_UPDATE,
        Permission.BILLING_CREATE,
        Permission.NOTIFICATION_READ,
    },
    UserRole.patient: {
        Permission.DEPARTMENT_READ,
        Permission.PATIENT_READ,
        Permission.PATIENT_UPDATE,
        Permission.PATIENT_DELETE,
        Permission.PROVIDER_READ,
        Permission.SLOT_READ,
        Permission.SLOT_RESERVE,
        Permission.SERVICE_READ,
        Permission.APPOINTMENT_CREATE,
        Permission.APPOINTMENT_READ,
        Permission.APPOINTMENT_CANCEL,
        Permission.APPOINTMENT_UPDATE,
        Permission.WAITLIST_JOIN,
        Permission.BILLING_CREATE,
        Permission.NOTIFICATION_READ,
    },
}
