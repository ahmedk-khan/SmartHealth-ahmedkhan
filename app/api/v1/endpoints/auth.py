from datetime import timedelta

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.core.authorization import require_admin
from app.core.rate_limit import limiter
from app.core.settings import settings
from app.models import User
from app.services import AuthService
from app.schemas.user import Token, UserCreate, UserLogin, UserRead, UserProfileRead, UserRole

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
    "/register/front-desk",
    response_model=UserRead,
    summary="Create a front-desk account",
    description="Creates a front-desk account. Only an authenticated administrator may use this endpoint.",
)
def register_front_desk(
    request: Request,
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return AuthService(db).register_front_desk(user_in)


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


@router.get(
    "/me",
    response_model=UserProfileRead,
    summary="Get current user profile",
    description="Returns the currently authenticated user's details including profile IDs based on their role.",
)
def get_me(current_user: User = Depends(get_current_user)):
    data = {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "created_at": current_user.created_at,
    }
    if current_user.role == UserRole.patient and current_user.patient:
        data.update({
            "patient_id": current_user.patient.id,
            "first_name": current_user.patient.first_name,
            "last_name": current_user.patient.last_name,
        })
    elif current_user.role == UserRole.provider and current_user.provider:
        data.update({
            "provider_id": current_user.provider.id,
            "bio": current_user.provider.bio,
            "specialty": current_user.provider.specialty,
            "department_id": current_user.provider.department_id,
        })
    return data
