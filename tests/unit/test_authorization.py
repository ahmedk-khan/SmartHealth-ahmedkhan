import pytest
from app.models.user import User, UserRole
from app.models import VisitStatus
from app.core.exceptions import ForbiddenError
from app.core.authorization.permissions import Permission, ROLE_PERMISSIONS
from app.core.authorization.service import authorize
from app.core.authorization.policies import (
    PatientPolicy,
    ProviderPolicy,
    SlotPolicy,
    ServicePolicy,
    AppointmentPolicy,
)


# Mock models/repositories for testing policies without db overhead
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
    def __init__(self, id, provider_id):
        self.id = id
        self.provider_id = provider_id


class MockService:
    def __init__(self, id, name=None):
        self.id = id
        self.name = name


class MockAppointment:
    def __init__(self, id, patient_id, provider_id):
        self.id = id
        self.patient_id = patient_id
        self.provider_id = provider_id


class MockPatientRepository:
    def __init__(self, patients_map):
        self._map = patients_map

    def get_by_user_id(self, user_id):
        return self._map.get(user_id)


class MockProviderRepository:
    def __init__(self, providers_map, services_map=None):
        self._map = providers_map
        self._services = services_map or {}

    def get_by_user_id(self, user_id):
        return self._map.get(user_id)

    def has_service(self, provider_id, service_id):
        return service_id in self._services.get(provider_id, set())


def test_role_permissions_mapping():
    # Admin has all permissions
    assert len(ROLE_PERMISSIONS[UserRole.admin]) == len(Permission)
    
    # Patient role check
    assert Permission.APPOINTMENT_CREATE in ROLE_PERMISSIONS[UserRole.patient]
    assert Permission.ANALYTICS_READ not in ROLE_PERMISSIONS[UserRole.patient]
    
    # Provider role check
    assert Permission.SERVICE_PUBLISH in ROLE_PERMISSIONS[UserRole.provider]
    assert Permission.ANALYTICS_READ not in ROLE_PERMISSIONS[UserRole.provider]


def test_authorize_coarse_grained():
    admin = User(role=UserRole.admin)
    patient = User(role=UserRole.patient)

    # Admin is allowed to reconcile analytics
    authorize(admin, Permission.ANALYTICS_RECONCILE)

    # Patient is not allowed
    with pytest.raises(ForbiddenError):
        authorize(patient, Permission.ANALYTICS_RECONCILE)


def test_patient_policy():
    admin = User(id=1, role=UserRole.admin)
    front_desk = User(id=2, role=UserRole.front_desk)
    patient_user = User(id=10, role=UserRole.patient)
    other_patient_user = User(id=11, role=UserRole.patient)

    patient_record = MockPatient(id=100, user_id=10)

    # Admin/front desk can read, update, delete
    assert PatientPolicy.can_read(admin, patient_record) is True
    assert PatientPolicy.can_read(front_desk, patient_record) is True

    # Patient can manage own profile
    assert PatientPolicy.can_read(patient_user, patient_record) is True
    assert PatientPolicy.can_update(patient_user, patient_record) is True
    assert PatientPolicy.can_delete(patient_user, patient_record) is True

    # Other patient cannot manage profile
    assert PatientPolicy.can_read(other_patient_user, patient_record) is False
    assert PatientPolicy.can_update(other_patient_user, patient_record) is False


def test_provider_policy():
    admin = User(id=1, role=UserRole.admin)
    provider_user = User(id=20, role=UserRole.provider)
    other_provider_user = User(id=21, role=UserRole.provider)

    provider_record = MockProvider(id=200, user_id=20)
    repo = MockProviderRepository({20: provider_record})

    # Admin can update
    assert ProviderPolicy.can_update(admin, provider_record) is True

    # Provider can update own record
    assert ProviderPolicy.can_update(provider_user, provider_record) is True

    # Other provider cannot update
    assert ProviderPolicy.can_update(other_provider_user, provider_record) is False

    # Provider record access
    assert ProviderPolicy.can_access_records(provider_user, provider_record, repo) is True
    assert ProviderPolicy.can_access_records(other_provider_user, provider_record, repo) is False
    assert ProviderPolicy.can_access_records(admin, provider_record, repo) is True


def test_slot_policy():
    admin = User(id=1, role=UserRole.admin)
    provider_user = User(id=20, role=UserRole.provider)
    other_provider_user = User(id=21, role=UserRole.provider)

    provider_record = MockProvider(id=200, user_id=20)
    other_provider_record = MockProvider(id=201, user_id=21)

    repo = MockProviderRepository({20: provider_record, 21: other_provider_record})
    slot = MockSlot(id=500, provider_id=200)

    # Can create slot
    assert SlotPolicy.can_create(admin, 200, repo) is True
    assert SlotPolicy.can_create(provider_user, 200, repo) is True
    assert SlotPolicy.can_create(provider_user, 201, repo) is False  # Cannot create for other provider

    # Can update slot
    assert SlotPolicy.can_update(admin, slot, repo) is True
    assert SlotPolicy.can_update(provider_user, slot, repo) is True
    assert SlotPolicy.can_update(other_provider_user, slot, repo) is False


def test_service_policy():
    admin = User(id=1, role=UserRole.admin)
    provider_user = User(id=20, role=UserRole.provider)
    other_provider_user = User(id=21, role=UserRole.provider)

    provider_record = MockProvider(id=200, user_id=20)
    other_provider_record = MockProvider(id=201, user_id=21)

    # provider 200 is linked to service 300
    repo = MockProviderRepository(
        {20: provider_record, 21: other_provider_record},
        {200: {300}}
    )
    service = MockService(id=300)

    assert ServicePolicy.can_update(admin, service, repo) is True
    assert ServicePolicy.can_update(provider_user, service, repo) is True
    assert ServicePolicy.can_update(other_provider_user, service, repo) is False


def test_appointment_policy():
    admin = User(id=1, role=UserRole.admin)
    front_desk = User(id=2, role=UserRole.front_desk)
    
    patient_user = User(id=10, role=UserRole.patient)
    other_patient_user = User(id=11, role=UserRole.patient)
    
    provider_user = User(id=20, role=UserRole.provider)
    other_provider_user = User(id=21, role=UserRole.provider)

    patient_record = MockPatient(id=100, user_id=10)
    other_patient_record = MockPatient(id=101, user_id=11)
    
    provider_record = MockProvider(id=200, user_id=20)
    other_provider_record = MockProvider(id=201, user_id=21)

    patient_repo = MockPatientRepository({10: patient_record, 11: other_patient_record})
    provider_repo = MockProviderRepository({20: provider_record, 21: other_provider_record})

    appointment = MockAppointment(id=1000, patient_id=100, provider_id=200)

    # Admin/front desk can read
    assert AppointmentPolicy.can_read(admin, appointment, patient_repo, provider_repo) is True
    assert AppointmentPolicy.can_read(front_desk, appointment, patient_repo, provider_repo) is True

    # Patient owning appointment can read
    assert AppointmentPolicy.can_read(patient_user, appointment, patient_repo, provider_repo) is True
    assert AppointmentPolicy.can_read(other_patient_user, appointment, patient_repo, provider_repo) is False

    # Provider owning appointment can read
    assert AppointmentPolicy.can_read(provider_user, appointment, patient_repo, provider_repo) is True
    assert AppointmentPolicy.can_read(other_provider_user, appointment, patient_repo, provider_repo) is False

    # Visit transitions
    # Admin can transition to CHECKED_IN, IN_PROGRESS, COMPLETED
    assert AppointmentPolicy.can_transition_visit(admin, appointment, VisitStatus.CHECKED_IN, provider_repo) is True
    assert AppointmentPolicy.can_transition_visit(admin, appointment, VisitStatus.IN_PROGRESS, provider_repo) is True
    assert AppointmentPolicy.can_transition_visit(admin, appointment, VisitStatus.COMPLETED, provider_repo) is True

    # Front desk can transition to CHECKED_IN but not IN_PROGRESS
    assert AppointmentPolicy.can_transition_visit(front_desk, appointment, VisitStatus.CHECKED_IN, provider_repo) is True
    assert AppointmentPolicy.can_transition_visit(front_desk, appointment, VisitStatus.IN_PROGRESS, provider_repo) is False

    # Owning provider can transition anything
    assert AppointmentPolicy.can_transition_visit(provider_user, appointment, VisitStatus.CHECKED_IN, provider_repo) is True
    assert AppointmentPolicy.can_transition_visit(provider_user, appointment, VisitStatus.IN_PROGRESS, provider_repo) is True
    assert AppointmentPolicy.can_transition_visit(provider_user, appointment, VisitStatus.COMPLETED, provider_repo) is True

    # Other provider cannot transition
    assert AppointmentPolicy.can_transition_visit(other_provider_user, appointment, VisitStatus.IN_PROGRESS, provider_repo) is False
