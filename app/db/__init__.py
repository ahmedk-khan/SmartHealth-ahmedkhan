from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.settings import settings


engine = create_engine(
	settings.database_url,
	future=True,
	pool_size=settings.db_pool_size,
	max_overflow=settings.db_max_overflow,
	pool_timeout=settings.db_pool_timeout,
	pool_recycle=settings.db_pool_recycle,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

__all__ = ["Base", "SessionLocal", "engine"]






