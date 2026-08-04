from datetime import datetime
from enum import Enum
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

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
    bio: Optional[str] = None
    department_id: Optional[int] = None


class ProviderCreate(ProviderBase):
    pass


class ProviderRead(ProviderBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServiceBase(BaseModel):
    name: str
    description: Optional[str] = None
    department_id: int
    is_published: bool = False


class ServiceCreate(ServiceBase):
    pass


class ServiceRead(ServiceBase):
    id: int
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


class PatientBase(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class PatientCreate(PatientBase):
    pass


class PatientRead(PatientBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    limit: int
    offset: int
