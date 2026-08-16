from fastapi import status

from app.core.exceptions import AppError
from app.core.metrics import record_login_attempt, record_user_registration
from app.core.security import create_access_token, get_password_hash, verify_password
from app.repositories import AuthRepository
from app.schemas.user import Token, UserCreate, UserLogin, UserRead
from app.services.base import BaseService


class AuthService(BaseService):
    """Authentication service with structured logging and metrics."""
    
    def __init__(self, db):
        super().__init__(db)
        self.repository = AuthRepository(db)

    def register(self, user_in: UserCreate) -> UserRead:
        """Register a new user with logging and metrics."""
        self.log_info("User registration attempt", operation="register", data={"email": "[REDACTED]"})
        
        existing = self.repository.get_user_by_email(user_in.email)
        if existing:
            self.log_warning("Registration failed: email already exists", operation="register", data={"existing": True})
            raise AppError("Email already registered", status_code=400, error_type="user_exists")
        
        user = self.repository.create_user(
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password),
            role=user_in.role,
        )
        
        self.log_info("User registered successfully", operation="register", data={"user_id": user.id, "role": user.role})
        
        # Record metrics
        try:
            record_user_registration(role=user.role)
        except Exception as exc:
            self.log_error("Failed to record registration metric", operation="register", data={"error": str(exc)})
        
        return UserRead.model_validate(user)

    def login(self, user_in: UserLogin) -> Token:
        """Authenticate user with logging and metrics."""
        self.log_info("Login attempt", operation="login", data={"email": "[REDACTED]"})
        
        user = self.repository.get_user_by_email(user_in.email)
        if not user or not verify_password(user_in.password, user.hashed_password):
            self.log_warning("Login failed: invalid credentials", operation="login")
            
            # Record failed login attempt
            try:
                record_login_attempt(success=False)
            except Exception as exc:
                self.log_error("Failed to record login failure metric", operation="login", data={"error": str(exc)})
            
            raise AppError("Incorrect email or password", status_code=status.HTTP_401_UNAUTHORIZED, error_type="invalid_credentials")

        access_token = create_access_token(subject=str(user.id))
        
        self.log_info("Login successful", operation="login", data={"user_id": user.id, "role": user.role})
        
        # Record successful login attempt
        try:
            record_login_attempt(success=True)
        except Exception as exc:
            self.log_error("Failed to record login success metric", operation="login", data={"error": str(exc)})
        
        return Token(access_token=access_token)