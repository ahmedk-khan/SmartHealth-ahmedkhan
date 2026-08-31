__all__ = [
    "AppointmentService",
    "AuthService",
    "ServiceManagementService",
    "SlotService",
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
    if name == "SlotService":
        from app.services.slot_service import SlotService

        return SlotService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")