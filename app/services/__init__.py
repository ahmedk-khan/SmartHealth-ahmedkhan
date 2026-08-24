__all__ = [
    "AppointmentService",
    "AuthService",
    "ServiceManagementService",
]


def __getattr__(name):
    if name == "AppointmentService":
        from app.services.appointment_service import AppointmentService

        return AppointmentService
    if name == "AuthService":
        from app.services.auth_service import AuthService

        return AuthService
    if name == "ServiceManagementService":
        from app.services.service_management import ServiceManagementService

        return ServiceManagementService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")