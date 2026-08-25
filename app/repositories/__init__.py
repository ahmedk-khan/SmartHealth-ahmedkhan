from app.repositories.appointments import AppointmentRepository
from app.repositories.auth import AuthRepository
from app.repositories.content_chunks import ContentChunkRepository
from app.repositories.departments import DepartmentRepository
from app.repositories.patients import PatientRepository
from app.repositories.providers import ProviderRepository
from app.repositories.services import ServiceRepository
from app.repositories.slots import SlotRepository
from app.repositories.waitlist import WaitlistRepository

__all__ = [
    "AppointmentRepository",
    "AuthRepository",
    "ContentChunkRepository",
    "DepartmentRepository",
    "PatientRepository",
    "ProviderRepository",
    "ServiceRepository",
    "SlotRepository",
    "WaitlistRepository",
]