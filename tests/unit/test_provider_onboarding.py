from app.models import Provider, User, UserRole
from app.repositories.auth import AuthRepository


def test_provider_registration_preserves_provider_role_before_profile_completion():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        user = AuthRepository(db).create_user("new-provider@example.com", "hash", UserRole.provider)
        assert user.role == UserRole.provider
        provider = db.query(Provider).filter(Provider.user_id == user.id).one_or_none()
        assert provider is not None
        assert provider.user_id == user.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
