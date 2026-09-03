from app.core.authorization import Permission
from app.core.authorization.service import check_permission
from app.core.exceptions import ForbiddenError, ProviderNotFoundError
from app.models import User, UserRole
from app.repositories import PatientRepository, ProviderRepository
from app.services.base import BaseService


class PatientService(BaseService):
    """Patient directory operations with role-scoped listing."""

    def __init__(self, db):
        super().__init__(db)
        self.patients = PatientRepository(db)
        self.providers = ProviderRepository(db)

    def list_patients(
        self,
        *,
        current_user: User,
        search: str | None = None,
        offset: int,
        limit: int,
    ) -> tuple[list, int]:
        check_permission(current_user, Permission.PATIENT_READ)

        if current_user.role == UserRole.provider:
            provider = self.providers.get_by_user_id(current_user.id)
            if not provider:
                raise ProviderNotFoundError("Provider profile not found")
            return self.patients.list_provider_patients(
                provider.id, offset=offset, limit=limit, search=search
            )

        if current_user.role in {UserRole.admin, UserRole.front_desk}:
            return self.patients.list_patients(offset=offset, limit=limit, search=search)

        raise ForbiddenError("Patient directory access is restricted to staff and providers")
