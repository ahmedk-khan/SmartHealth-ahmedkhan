from typing import Callable, Generator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.db import SessionLocal
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise AppError("Invalid authentication credentials", status_code=401, error_type="invalid_token")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise AppError("User not found", status_code=401, error_type="user_not_found")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise AppError(
                "Operation forbidden",
                status_code=403,
                error_type="forbidden",
            )
        return current_user

    return dependency
