import datetime
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.exceptions import AppError
from app.core.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, expires_delta: Optional[datetime.timedelta] = None) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_delta is None:
        expires_delta = datetime.timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError as exc:
        raise AppError(
            "Could not validate credentials",
            status_code=401,
            error_type="invalid_token",
            detail=str(exc),
        )
