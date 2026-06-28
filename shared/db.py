"""Async SQLAlchemy 2.0 engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.postgres_dsn,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
    future=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a DB session."""
    async with SessionLocal() as session:
        yield session
