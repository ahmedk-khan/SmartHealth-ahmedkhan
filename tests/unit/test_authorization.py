import pytest
from types import SimpleNamespace

from app.models.user import User, UserRole
from app.models import VisitStatus
from app.core.exceptions import ForbiddenError
from app.core.authorization.permissions import Permission, ROLE_PERMISSIONS
from app.core.authorization.service import check_permission, ensure_admin_or_front_desk
from app.core.authorization.policies import (
    PatientOwnershipGuard,
    ProviderOwnershipGuard,
    SlotOwnershipGuard,
    ServiceOwnershipGuard,
    AppointmentOwnershipGuard,
    VisitTransitionGuard,
    NoShowGuard,
)


class MockPatient:
    def __init__(self, id, user_id):
        self.id = id
        self.user_id = user_id


class MockProvider:
    def __init__(self, id, user_id, bio=None, department_id=None, specialty=None):
        self.id = id
        self.user_id = user_id
        self.bio = bio
        self.department_id = department_id
        self.specialty = specialty


class MockSlot:
    def __init__(self, id, provider_id, provider=None):
        self.id = id
        self.provider_id = provider_id
        self.provider = provider


class MockService:
    def __init__(self, id, name=None):
        self.id = id
        self.name = name


class MockAppointment:
    def __init__(self, id, patient_id, provider_id, patient=None, provider=None):
        self.id = id
        self.patient_id = patient_id
        self.provider_id = provider_id
        self.patient = patient
        self.provider = provider


def _user(user_id: int, role: UserRole, *, patient=None, provider=None):
    return SimpleNamespace(id=user_id, role=role, patient=patient, provider=provider)


def test_role_permissions_mapping():
    assert len(ROLE_PERMISSIONS[UserRole.admin]) == len(Permission)
    assert Permission.APPOINTMENT_CREATE in ROLE_PERMISSIONS[UserRole.patient]
    assert Permission.ANALYTICS_READ not in ROLE_PERMISSIONS[UserRole.patient]
    assert Permission.SERVICE_PUBLISH in ROLE_PERMISSIONS[UserRole.provider]
    assert Permission.ANALYTICS_READ not in ROLE_PERMISSIONS[UserRole.provider]


def test_check_permission_coarse_grained():
    admin = User(role=UserRole.admin)
    patient = User(role=UserRole.patient)

    check_permission(admin, Permission.ANALYTICS_RECONCILE)

    with pytest.raises(ForbiddenError):
        check_permission(patient, Permission.ANALYTICS_RECONCILE)


def test_ensure_admin_or_front_desk():
    ensure_admin_or_front_desk(User(role=UserRole.admin))
    ensure_admin_or_front_desk(User(role=UserRole.front_desk))

    with pytest.raises(ForbiddenError):
        ensure_admin_or_front_desk(User(role=UserRole.provider))


def test_patient_ownership_guard():
    patient_record = MockPatient(id=100, user_id=10)
    owner = _user(10, UserRole.patient, patient=patient_record)
    other_patient = _user(11, UserRole.patient, patient=MockPatient(id=101, user_id=11))

    assert PatientOwnershipGuard(User(id=1, role=UserRole.admin), patient_record).passed() is True
    assert PatientOwnershipGuard(owner, patient_record).passed() is True
    assert PatientOwnershipGuard(other_patient, patient_record).passed() is False


def test_provider_ownership_guard():
    provider_record = MockProvider(id=200, user_id=20)
    owner = _user(20, UserRole.provider, provider=provider_record)
    other_provider = _user(21, UserRole.provider, provider=MockProvider(id=201, user_id=21))

    assert ProviderOwnershipGuard(owner, provider_record).passed() is True
    assert ProviderOwnershipGuard(other_provider, provider_record).passed() is False


def test_service_ownership_guard_uses_service_providers_relationship():
    owner = _user(20, UserRole.provider, provider=MockProvider(id=200, user_id=20))
    other_provider = _user(21, UserRole.provider, provider=MockProvider(id=201, user_id=21))
    service = MockService(id=500)
    service.providers = [MockProvider(id=200, user_id=20)]

    assert ServiceOwnershipGuard(owner, service).passed() is True
    assert ServiceOwnershipGuard(other_provider, service).passed() is False


def test_slot_ownership_guard():
    provider_record = MockProvider(id=200, user_id=20)
    owner = _user(20, UserRole.provider, provider=provider_record)
    other_provider = _user(21, UserRole.provider, provider=MockProvider(id=201, user_id=21))
    slot = MockSlot(id=500, provider_id=200, provider=provider_record)

    assert SlotOwnershipGuard(owner, slot).passed() is True
    assert SlotOwnershipGuard(other_provider, slot).passed() is False


def test_appointment_ownership_guard():
    patient_record = MockPatient(id=100, user_id=10)
    provider_record = MockProvider(id=200, user_id=20)
    appointment = MockAppointment(
        id=1000,
        patient_id=100,
        provider_id=200,
        patient=patient_record,
        provider=provider_record,
    )

    patient_user = _user(10, UserRole.patient, patient=patient_record)
    other_patient = _user(11, UserRole.patient, patient=MockPatient(id=101, user_id=11))
    provider_user = _user(20, UserRole.provider, provider=provider_record)
    other_provider = _user(21, UserRole.provider, provider=MockProvider(id=201, user_id=21))

    assert AppointmentOwnershipGuard(User(id=1, role=UserRole.admin), appointment).passed() is True
    assert AppointmentOwnershipGuard(patient_user, appointment).passed() is True
    assert AppointmentOwnershipGuard(other_patient, appointment).passed() is False
    assert AppointmentOwnershipGuard(provider_user, appointment).passed() is True
    assert AppointmentOwnershipGuard(other_provider, appointment).passed() is False


def test_visit_transition_guard():
    provider_record = MockProvider(id=200, user_id=20)
    appointment = MockAppointment(id=1000, patient_id=100, provider_id=200, provider=provider_record)
    provider_user = _user(20, UserRole.provider, provider=provider_record)
    other_provider = _user(21, UserRole.provider, provider=MockProvider(id=201, user_id=21))

    assert VisitTransitionGuard(User(id=1, role=UserRole.admin), appointment, VisitStatus.CHECKED_IN).passed() is True
    assert VisitTransitionGuard(User(id=2, role=UserRole.front_desk), appointment, VisitStatus.CHECKED_IN).passed() is True
    assert VisitTransitionGuard(User(id=2, role=UserRole.front_desk), appointment, VisitStatus.IN_PROGRESS).passed() is False
    assert VisitTransitionGuard(provider_user, appointment, VisitStatus.IN_PROGRESS).passed() is True
    assert VisitTransitionGuard(other_provider, appointment, VisitStatus.IN_PROGRESS).passed() is False


def test_no_show_guard():
    provider_record = MockProvider(id=200, user_id=20)
    appointment = MockAppointment(id=1000, patient_id=100, provider_id=200, provider=provider_record)
    provider_user = _user(20, UserRole.provider, provider=provider_record)
    other_provider = _user(21, UserRole.provider, provider=MockProvider(id=201, user_id=21))

    assert NoShowGuard(User(id=2, role=UserRole.front_desk), appointment).passed() is True
    assert NoShowGuard(provider_user, appointment).passed() is True
    assert NoShowGuard(other_provider, appointment).passed() is False
