"""Create demo login users without creating any domain records."""

from app.core.security import get_password_hash
from app.db import SessionLocal
from app.models import User, UserRole
from app.repositories import AuthRepository


DEMO_USERS = (
    ("admin@example.com", "secret123", UserRole.admin),
    ("provider@example.com", "secret123", UserRole.provider),
    ("patient@example.com", "secret123", UserRole.patient),
    ("frontdesk@example.com", "secret123", UserRole.front_desk),
    ("demo@gmail.com", "adminadmin", UserRole.admin),
)


def seed_users() -> None:
    db = SessionLocal()
    repository = AuthRepository(db)
    try:
        for email, password, role in DEMO_USERS:
            user = repository.get_user_by_email(email)
            if user is None:
                user = User(email=email, is_active=True)
                db.add(user)
            user.hashed_password = get_password_hash(password)
            user.role = role
            user.is_active = True
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_users()