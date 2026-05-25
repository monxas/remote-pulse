"""Pytest fixtures for async testing."""
import asyncio
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rp_server.auth import create_enrollment_token
from rp_server.database import get_db
from rp_server.main import app
from rp_server.models import Base, Enrollment


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Create test database using in-memory SQLite.

    Note: For production tests, use a real PostgreSQL testcontainer.
    SQLite lacks some PG features (gen_random_uuid, JSONB) but sufficient for basic tests.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client with overridden DB dependency."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def enrollment_token(test_db: AsyncSession) -> str:
    """Create a valid enrollment token for tests."""
    token, jti = create_enrollment_token(
        group_name="test-group",
        issued_by="pytest",
        ttl_hours=1,
        max_uses=1,
    )

    # Create corresponding enrollment record
    enrollment = Enrollment(
        token_jti=jti,
        issued_by="pytest",
        group_name="test-group",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        max_uses=1,
        used_count=0,
    )

    test_db.add(enrollment)
    await test_db.commit()

    return token
