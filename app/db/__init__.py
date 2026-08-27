from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.settings import settings


engine = create_engine(settings.database_url, future=True) # engine => the connector btw the orm and databse
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

__all__ = ["Base", "SessionLocal", "engine"]



















