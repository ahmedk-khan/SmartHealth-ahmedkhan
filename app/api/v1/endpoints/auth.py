from datetime import timedelta

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.rate_limit import limiter
from app.core.settings import settings
from app.services import AuthService
from app.schemas.user import Token, UserCreate, UserLogin, UserRead

router = APIRouter(tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    tags=["auth"],
    summary="Register a new user",
    description="Creates a new user account and returns the created profile. This endpoint is used for onboarding new patients or staff.",
)
@limiter.limit(lambda: settings.auth_register_rate_limit)
def register(request: Request, user_in: UserCreate, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.register(user_in)


@router.post(
    "/login",
    response_model=Token,
    tags=["auth"],
    summary="Authenticate user",
    description="Validates user credentials and returns a JWT access token for authenticated API access.",
)
@limiter.limit(lambda: settings.auth_login_rate_limit)
def login(request: Request, user_in: UserLogin, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.login(user_in)


@router.post(
    "/token",
    response_model=Token,
    include_in_schema=False,
    summary="OAuth2 token login",
    description="OAuth2-compatible form login used by Swagger UI and other OAuth2 clients.",
)
def token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.login(UserLogin(email=form_data.username, password=form_data.password))
