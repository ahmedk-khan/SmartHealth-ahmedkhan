from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=120), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    providers = relationship("Provider", back_populates="department", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="department", cascade="all, delete-orphan")
