from datetime import datetime
from enum import Enum
from typing import Generic, List, Optional, TypeVar
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class DepartmentBase(BaseModel):
    name: str
    description: Optional[str] = None


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentRead(DepartmentBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProviderBase(BaseModel):
    user_id: Optional[int] = None
    bio: Optional[str] = None
    specialty: Optional[str] = None
    department_id: Optional[int] = None


class ProviderCreate(ProviderBase):
    pass


class ProviderUpdate(BaseModel):
    bio: Optional[str] = None
    specialty: Optional[str] = None
    department_id: Optional[int] = None


class ProviderRead(ProviderBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHING = "UNPUBLISHING"
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISH_FAILED = "PUBLISH_FAILED"


class ServiceBase(BaseModel):
    name: str
    description: Optional[str] = None
    specialty: Optional[str] = None
    preparation_instructions: Optional[str] = None
    department_id: int
    price: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2, max_digits=10)
    is_published: bool = False


class ServiceCreate(ServiceBase):
    pass


class ServiceRead(ServiceBase):
    id: int
    status: ServiceStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class SlotBase(BaseModel):
    provider_id: int
    service_id: int
    patient_id: Optional[int] = None
    status: SlotStatus = SlotStatus.AVAILABLE
    start_datetime: datetime
    end_datetime: datetime


class SlotCreate(SlotBase):
    pass


class SlotRead(SlotBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SLOT_RESERVED = "SLOT_RESERVED"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class VisitStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class AppointmentBase(BaseModel):
    patient_id: int
    provider_id: int
    service_id: int
    slot_id: int
    status: AppointmentStatus = AppointmentStatus.PENDING
    visit_status: VisitStatus = VisitStatus.NOT_STARTED


class AppointmentCreate(BaseModel):
    slot_id: int

    model_config = ConfigDict(extra="forbid")


class AppointmentRead(AppointmentBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WaitlistEntryRead(BaseModel):
    id: int
    slot_id: int
    patient_id: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AppointmentStatusHistoryBase(BaseModel):
    appointment_id: int
    status: AppointmentStatus


class AppointmentStatusHistoryRead(AppointmentStatusHistoryBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BillingStatus(str, Enum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    PENDING = "PENDING"


class BillingBase(BaseModel):
    amount: float = 0.0
    status: BillingStatus = BillingStatus.PENDING


class BillingRead(BillingBase):
    id: int
    appointment_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PatientBase(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class PatientRead(PatientBase):
    id: int
    user_id: int
    email: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    limit: int
    offset: int
