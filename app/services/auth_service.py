from fastapi import status

from app.core.exceptions import AppError
from app.core.security import create_access_token, get_password_hash, verify_password
from app.repositories import AuthRepository
from app.schemas.user import Token, UserCreate, UserLogin, UserRead
from app.services.base import BaseService


class AuthService(BaseService):
    def __init__(self, db):
        super().__init__(db)
        self.repository = AuthRepository(db)

    def register(self, user_in: UserCreate) -> UserRead:
        existing = self.repository.get_user_by_email(user_in.email)
        if existing:
            raise AppError("Email already registered", status_code=400, error_type="user_exists")
        user = self.repository.create_user(
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password),
            role=user_in.role,
        )
        return UserRead.model_validate(user)

    def login(self, user_in: UserLogin) -> Token:
        user = self.repository.get_user_by_email(user_in.email)
        if not user or not verify_password(user_in.password, user.hashed_password):
            raise AppError("Incorrect email or password", status_code=status.HTTP_401_UNAUTHORIZED, error_type="invalid_credentials")

        access_token = create_access_token(subject=str(user.id))
        return Token(access_token=access_token)