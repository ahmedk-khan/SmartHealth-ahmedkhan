from collections.abc import Generator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import db as db_module
from app.core.ai_controls import AIRedisStore, get_ai_redis_store
from app.core.exceptions import RateLimitError, UnauthorizedError
from app.core.security import decode_access_token
from app.models import User
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
        raise UnauthorizedError("Could not validate credentials", code="INVALID_TOKEN")
    try:
        user = AuthRepository(db).get_user_by_id(int(user_id))
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("Could not validate credentials", code="INVALID_TOKEN") from exc
    if not user:
        raise UnauthorizedError("User not found", code="USER_NOT_FOUND")
    if not user.is_active:
        raise UnauthorizedError("Inactive user", code="INACTIVE_USER")
    return user


async def require_ai_rate_limit(
    current_user: User = Depends(get_current_user),
    ai_store: AIRedisStore = Depends(get_ai_redis_store),
) -> User:
    """Reject AI requests when the per-user Redis rate limit is exceeded."""
    if not await ai_store.allow_request(current_user.id):
        raise RateLimitError("AI request rate limit exceeded")
    return current_user
