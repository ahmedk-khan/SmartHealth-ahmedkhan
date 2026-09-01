__all__ = [
    "AppointmentService",
    "AuthService",
    "ServiceManagementService",
    "SlotService",
    "hybrid_search_services",
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
    if name == "hybrid_search_services":
        from app.services.hybrid_search_service import hybrid_search_services

        return hybrid_search_services
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")