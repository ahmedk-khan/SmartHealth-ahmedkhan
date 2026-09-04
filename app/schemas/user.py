from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class UserRole(str, Enum):
    patient = "patient"
    provider = "provider"
    front_desk = "front_desk"
    admin = "admin"


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str
    role: Optional[UserRole] = UserRole.patient
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(UserBase):
    id: int
    role: UserRole
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    exp: int


class UserProfileRead(BaseModel):
    id: int
    email: EmailStr
    role: UserRole
    created_at: datetime
    patient_id: Optional[int] = None
    provider_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    specialty: Optional[str] = None
    department_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
