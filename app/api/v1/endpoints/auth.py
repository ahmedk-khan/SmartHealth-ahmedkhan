from datetime import timedelta

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.exceptions import AppError
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models import Patient, User, UserRole
from app.schemas.user import Token, UserCreate, UserLogin, UserRead

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=UserRead)

def register(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise AppError("Email already registered", status_code=400, error_type="user_exists")
    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role,
    )
    db.add(user)
    db.flush()
    if user.role == UserRole.patient:
        db.add(Patient(user_id=user.id))
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/login", response_model=Token)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_in.email).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise AppError("Incorrect email or password", status_code=status.HTTP_401_UNAUTHORIZED, error_type="invalid_credentials")

    access_token_expires = timedelta(minutes=60)
    access_token = create_access_token(subject=str(user.id), expires_delta=access_token_expires)
    return Token(access_token=access_token)
