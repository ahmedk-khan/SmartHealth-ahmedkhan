from app.models import Patient, Provider, User, UserRole
from app.repositories.base import BaseRepository


class AuthRepository(BaseRepository):
    def ensure_seed_user(self, email: str, hashed_password: str, role: UserRole) -> User:
        """Return an active seed user, creating or reactivating it as needed."""
        existing_user = self.get_user_by_email(email)
        if existing_user:
            if not existing_user.is_active:
                existing_user.is_active = True
                self.commit()
                self.refresh(existing_user)
            return existing_user
        user = User(email=email, hashed_password=hashed_password, role=role, is_active=True)
        self.add(user)
        self.commit()
        self.refresh(user)
        return user

    def get_user_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email).first()

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def create_user(self, email: str, hashed_password: str, role: UserRole, first_name: str | None = None, last_name: str | None = None) -> User:
        user = User(email=email, hashed_password=hashed_password, role=role)
        self.add(user)
        self.flush()
        if role == UserRole.patient:
            patient = self.db.query(Patient).filter(Patient.user_id == user.id).first()
            if patient is None:
                self.add(Patient(user_id=user.id, first_name=first_name, last_name=last_name))
        elif role == UserRole.provider:
            provider = self.db.query(Provider).filter(Provider.user_id == user.id).first()
            if provider is None:
                self.add(Provider(user_id=user.id))
        self.commit()
        self.refresh(user)
        return user
