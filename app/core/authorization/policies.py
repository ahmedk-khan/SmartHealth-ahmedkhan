"""
Fine-Grained Access Control Guards

Used inline in endpoints for resource-level ownership/hierarchy checks.
These implement the SECOND tier of authorization (after coarse permission check).

Example:
    @app.get("/patients/{id}")
    def get_patient(id: int, user: User = Depends(require_permission(Permission.PATIENT_READ))):
        patient = fetch_patient(id)
        if not PatientOwnershipGuard(user, patient).passed():
            raise ForbiddenError()
        return patient
"""

from app.models import User, UserRole, VisitStatus
from app.core.exceptions import ForbiddenError


class Guard:
    """Base guard class for resource access checks"""
    
    def __init__(self, user: User):
        self.user = user
    
    def passed(self) -> bool:
        """Return True if user has access, False otherwise"""
        raise NotImplementedError
    
    def enforce(self) -> None:
        """Raise ForbiddenError if access denied"""
        if not self.passed():
            raise ForbiddenError("Access denied")


class PatientOwnershipGuard(Guard):
    """Check patient ownership: user is patient or staff"""
    
    def __init__(self, user: User, patient):
        super().__init__(user)
        self.patient = patient
    
    def passed(self) -> bool:
        # Staff (admin, front_desk) always allowed
        if self.user.role in {UserRole.admin, UserRole.front_desk}:
            return True
        # Patient can only access own profile
        return self.user.id == self.patient.user_id


class ProviderOwnershipGuard(Guard):
    """Check provider ownership: user is provider owner or staff"""
    
    def __init__(self, user: User, provider):
        super().__init__(user)
        self.provider = provider
    
    def passed(self) -> bool:
        # Staff always allowed
        if self.user.role in {UserRole.admin, UserRole.front_desk}:
            return True
        # Provider can only access own record
        if self.user.role == UserRole.provider:
            return self.provider.user_id == self.user.id
        return False


class SlotOwnershipGuard(Guard):
    """Check slot ownership: user is slot provider or staff"""
    
    def __init__(self, user: User, slot):
        super().__init__(user)
        self.slot = slot
    
    def passed(self) -> bool:
        # Staff always allowed
        if self.user.role in {UserRole.admin, UserRole.front_desk}:
            return True
        # Provider can only manage own slots
        if self.user.role == UserRole.provider:
            provider = getattr(self.slot, "provider", self.slot)
            return getattr(provider, "user_id", None) == self.user.id
        return False


class ServiceOwnershipGuard(Guard):
    """Check service ownership: user is service owner or staff"""
    
    def __init__(self, user: User, service):
        super().__init__(user)
        self.service = service
    
    def passed(self) -> bool:
        # Staff always allowed
        if self.user.role in {UserRole.admin, UserRole.front_desk}:
            return True
        # Provider can only manage own services
        if self.user.role == UserRole.provider:
            return any(provider.user_id == self.user.id for provider in self.service.providers)
        return False


class AppointmentOwnershipGuard(Guard):
    """Check appointment ownership: user is patient/provider or staff"""
    
    def __init__(self, user: User, appointment):
        super().__init__(user)
        self.appointment = appointment
    
    def passed(self) -> bool:
        # Staff always allowed
        if self.user.role in {UserRole.admin, UserRole.front_desk}:
            return True
        # Providers can access own appointments
        if self.user.role == UserRole.provider:
            return self.appointment.provider_id is not None
        # Patients can access own appointments
        if self.user.role == UserRole.patient:
            return self.appointment.patient_id is not None
        return False


class VisitTransitionGuard(Guard):
    """Check appointment visit state transition permissions"""
    
    def __init__(self, user: User, appointment, target_status):
        super().__init__(user)
        self.appointment = appointment
        self.target_status = target_status
    
    def passed(self) -> bool:
        # Admin always allowed
        if self.user.role == UserRole.admin:
            return True
        
        # Front desk can check-in patients
        if self.user.role == UserRole.front_desk:
            return self.target_status == VisitStatus.CHECKED_IN
        
        # Providers can transition visits for their appointments
        if self.user.role == UserRole.provider:
            return self.appointment.provider_id is not None
        
        return False


class NoShowGuard(Guard):
    """Check permission to mark appointment as no-show"""
    
    def __init__(self, user: User, appointment):
        super().__init__(user)
        self.appointment = appointment
    
    def passed(self) -> bool:
        # Staff can mark as no-show
        if self.user.role in {UserRole.admin, UserRole.front_desk}:
            return True
        # Provider can mark own appointments as no-show
        if self.user.role == UserRole.provider:
            return self.appointment.provider_id is not None
        return False
