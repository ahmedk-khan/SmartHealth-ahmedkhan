"""Shared database session helper for Temporal activities."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app import db as db_module


@contextmanager
def activity_session() -> Generator[Session, None, None]:
    """Yield a sync SQLAlchemy session for worker activities."""
    db: Session = db_module.SessionLocal()
    try:
        yield db
    finally:
        db.close()
