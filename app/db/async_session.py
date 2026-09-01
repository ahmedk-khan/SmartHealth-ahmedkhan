"""Async SQLAlchemy session factory used by I/O-bound worker activities."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings


def _async_database_url() -> str:
    url = settings.database_url or ""
    if url.startswith("sqlite+pysqlite://"):
        return url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    return url


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session; callers own transaction boundaries."""
    engine = create_async_engine(_async_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
