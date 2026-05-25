"""Database session factory and async connection management."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rp_server.config import settings

engine = create_async_engine(
    str(settings.postgres_url),
    echo=settings.log_level == "DEBUG",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: provide database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


DbSession = Annotated[AsyncSession, Depends(get_db)]
