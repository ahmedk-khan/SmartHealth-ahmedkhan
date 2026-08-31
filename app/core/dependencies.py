from collections.abc import Callable, Generator
from enum import Enum

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import db as db_module
from app.core.exceptions import AppError, UnauthorizedError, ForbiddenError, invalid_token_error
from app.core.security import decode_access_token
from app.models import User, UserRole
from app.repositories.auth import AuthRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_db() -> Generator[Session, None, None]:
    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise invalid_token_error()
    try:
        user = AuthRepository(db).get_user_by_id(int(user_id))
    except (TypeError, ValueError) as exc:
        raise invalid_token_error() from exc
    if not user:
        raise UnauthorizedError("User not found", code="USER_NOT_FOUND")
    if not user.is_active:
        raise UnauthorizedError("Inactive user", code="INACTIVE_USER")
    return user


def _role_value(role: str | UserRole | Enum) -> str:
    if isinstance(role, UserRole):
        return role.value
    if isinstance(role, Enum):
        return str(role.value)
    return str(role)


def require_role(*roles: str | UserRole | Enum) -> Callable[[User], User]:
    allowed = {_role_value(role) for role in roles}

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in allowed:
            raise ForbiddenError()
        return current_user

    return dependency


def require_roles(*roles: str | UserRole | Enum) -> Callable[[User], User]:
    return require_role(*roles)


def require_admin_or_front_desk(current_user: User = Depends(require_role(UserRole.admin, UserRole.front_desk))) -> User:
    return current_user


def require_staff(current_user: User = Depends(require_role(UserRole.admin, UserRole.front_desk, UserRole.provider))) -> User:
    return current_user


def require_provider(current_user: User = Depends(require_role(UserRole.provider))) -> User:
    return current_user


def require_patient(current_user: User = Depends(require_role(UserRole.patient))) -> User:
    return current_user
