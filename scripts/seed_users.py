"""Create demo login users without creating any domain records."""

from app.core.security import get_password_hash
from app.db import SessionLocal
from app.models import UserRole
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
            repository.ensure_seed_user(email, get_password_hash(password), role)
    finally:
        db.close()


if __name__ == "__main__":
    seed_users()