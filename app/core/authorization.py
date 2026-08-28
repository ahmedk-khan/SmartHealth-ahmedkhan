from collections.abc import Collection

from app.core.exceptions import forbidden_error
from app.models import User, UserRole


def ensure_role(current_user: User, allowed_roles: Collection[UserRole], message: str = "Forbidden") -> None:
    if current_user.role not in allowed_roles:
        raise forbidden_error(message)


def ensure_patient_or_roles(
    current_user: User,
    patient_repository,
    patient_id: int,
    allowed_roles: Collection[UserRole],
) -> None:
    if current_user.role == UserRole.patient:
        patient = patient_repository.get_by_user_id(current_user.id)
        if not patient or patient_id != patient.id:
            raise forbidden_error()
    elif current_user.role not in allowed_roles:
        raise forbidden_error()


def ensure_appointment_access(appointment, current_user: User, patient_repository, provider_repository) -> None:
    ensure_provider_ownership(appointment.provider_id, current_user, provider_repository)
    ensure_patient_or_roles(
        current_user,
        patient_repository,
        appointment.patient_id,
        {UserRole.admin, UserRole.front_desk, UserRole.provider},
    )


def ensure_patient_access(patient, current_user: User) -> None:
    if current_user.role not in {UserRole.admin, UserRole.front_desk} and current_user.id != patient.user_id:
        raise forbidden_error()


def ensure_provider_ownership(
    provider_id: int,
    current_user: User,
    provider_repository,
    message: str = "Forbidden",
) -> None:
    if current_user.role != UserRole.provider:
        return
    provider = provider_repository.get_by_user_id(current_user.id)
    if not provider or provider.id != provider_id:
        raise forbidden_error(message)


def ensure_provider_record_ownership(provider, current_user: User) -> None:
    if current_user.role == UserRole.provider and provider.user_id != current_user.id:
        raise forbidden_error()


def ensure_provider_record_access(provider_id: int, current_user: User, provider_repository) -> None:
    if current_user.role == UserRole.provider:
        own_provider = provider_repository.get_by_user_id(current_user.id)
        if not own_provider or own_provider.id != provider_id:
            raise forbidden_error()
    elif current_user.role not in {UserRole.admin, UserRole.front_desk}:
        raise forbidden_error()
