from app.models import User, UserRole, VisitStatus

class PatientPolicy:
    @staticmethod
    def can_read(user: User, patient) -> bool:
        return user.role in {UserRole.admin, UserRole.front_desk} or user.id == patient.user_id

    @staticmethod
    def can_update(user: User, patient) -> bool:
        return user.role in {UserRole.admin, UserRole.front_desk} or user.id == patient.user_id

    @staticmethod
    def can_delete(user: User, patient) -> bool:
        return user.role in {UserRole.admin, UserRole.front_desk} or user.id == patient.user_id


class ProviderPolicy:
    @staticmethod
    def can_update(user: User, provider) -> bool:
        if user.role == UserRole.provider:
            return provider.user_id == user.id
        return user.role in {UserRole.admin, UserRole.front_desk}

    @staticmethod
    def can_access_records(user: User, provider, provider_repository) -> bool:
        if user.role == UserRole.provider:
            own_provider = provider_repository.get_by_user_id(user.id)
            return own_provider is not None and own_provider.id == provider.id
        return user.role in {UserRole.admin, UserRole.front_desk}


class SlotPolicy:
    @staticmethod
    def can_create(user: User, provider_id: int, provider_repository) -> bool:
        if user.role == UserRole.provider:
            own_provider = provider_repository.get_by_user_id(user.id)
            return own_provider is not None and own_provider.id == provider_id
        return user.role in {UserRole.admin, UserRole.front_desk}

    @staticmethod
    def can_update(user: User, slot, provider_repository) -> bool:
        if user.role == UserRole.provider:
            own_provider = provider_repository.get_by_user_id(user.id)
            return own_provider is not None and own_provider.id == slot.provider_id
        return user.role in {UserRole.admin, UserRole.front_desk}

    @staticmethod
    def can_delete(user: User, slot, provider_repository) -> bool:
        if user.role == UserRole.provider:
            own_provider = provider_repository.get_by_user_id(user.id)
            return own_provider is not None and own_provider.id == slot.provider_id
        return user.role in {UserRole.admin, UserRole.front_desk}


class ServicePolicy:
    @staticmethod
    def can_update(user: User, service, provider_repository) -> bool:
        if user.role == UserRole.provider:
            provider = provider_repository.get_by_user_id(user.id)
            return provider is not None and provider_repository.has_service(provider.id, service.id)
        return user.role in {UserRole.admin, UserRole.front_desk}

    @staticmethod
    def can_publish(user: User, service, provider_repository) -> bool:
        if user.role == UserRole.provider:
            provider = provider_repository.get_by_user_id(user.id)
            return provider is not None and provider_repository.has_service(provider.id, service.id)
        return user.role in {UserRole.admin, UserRole.front_desk}

    @staticmethod
    def can_unpublish(user: User, service, provider_repository) -> bool:
        if user.role == UserRole.provider:
            provider = provider_repository.get_by_user_id(user.id)
            return provider is not None and provider_repository.has_service(provider.id, service.id)
        return user.role in {UserRole.admin, UserRole.front_desk}

    @staticmethod
    def can_access_status(user: User, service, provider_repository) -> bool:
        if user.role == UserRole.provider:
            provider = provider_repository.get_by_user_id(user.id)
            return provider is not None and provider_repository.has_service(provider.id, service.id)
        return user.role in {UserRole.admin, UserRole.front_desk}


class AppointmentPolicy:
    @staticmethod
    def can_read(user: User, appointment, patient_repository, provider_repository) -> bool:
        if user.role == UserRole.provider:
            provider = provider_repository.get_by_user_id(user.id)
            return provider is not None and provider.id == appointment.provider_id
        if user.role == UserRole.patient:
            patient = patient_repository.get_by_user_id(user.id)
            return patient is not None and patient.id == appointment.patient_id
        return user.role in {UserRole.admin, UserRole.front_desk}

    @staticmethod
    def can_cancel(user: User, appointment, patient_repository, provider_repository) -> bool:
        return AppointmentPolicy.can_read(user, appointment, patient_repository, provider_repository)

    @staticmethod
    def can_reschedule(user: User, appointment, patient_repository, provider_repository) -> bool:
        return AppointmentPolicy.can_read(user, appointment, patient_repository, provider_repository)

    @staticmethod
    def can_billing_precheck(user: User, appointment, patient_repository, provider_repository) -> bool:
        return AppointmentPolicy.can_read(user, appointment, patient_repository, provider_repository)

    @staticmethod
    def can_transition_visit(user: User, appointment, target_status, provider_repository) -> bool:
        if user.role == UserRole.provider:
            provider = provider_repository.get_by_user_id(user.id)
            return provider is not None and provider.id == appointment.provider_id
        if target_status == VisitStatus.CHECKED_IN:
            return user.role in {UserRole.admin, UserRole.front_desk}
        return user.role == UserRole.admin

    @staticmethod
    def can_mark_no_show(user: User, appointment, provider_repository) -> bool:
        if user.role == UserRole.provider:
            provider = provider_repository.get_by_user_id(user.id)
            return provider is not None and provider.id == appointment.provider_id
        return user.role in {UserRole.admin, UserRole.front_desk}
