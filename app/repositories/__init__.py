from app.repositories.appointments import AppointmentRepository
from app.repositories.auth import AuthRepository
from app.repositories.departments import DepartmentRepository
from app.repositories.patients import PatientRepository
from app.repositories.providers import ProviderRepository
from app.repositories.services import ServiceRepository
from app.repositories.slots import SlotRepository

__all__ = [
    "AppointmentRepository",
    "AuthRepository",
    "DepartmentRepository",
    "PatientRepository",
    "ProviderRepository",
    "ServiceRepository",
    "SlotRepository",
]