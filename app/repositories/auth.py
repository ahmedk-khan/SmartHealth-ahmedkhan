from sqlalchemy.orm import Session

from app.models import Patient, User, UserRole
from app.repositories.base import BaseRepository


class AuthRepository(BaseRepository):
    def get_user_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email).first()

    def create_user(self, email: str, hashed_password: str, role: UserRole) -> User:
        user = User(email=email, hashed_password=hashed_password, role=role)
        self.db.add(user)
        self.db.flush()
        if role == UserRole.patient:
            patient = self.db.query(Patient).filter(Patient.user_id == user.id).first()
            if patient is None:
                self.db.add(Patient(user_id=user.id))
        self.db.commit()
        self.db.refresh(user)
        return user