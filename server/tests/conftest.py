"""Pytest fixtures for async testing."""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone

import json as _json
import uuid as _uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import ColumnDefault
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

# --- SQLite compatibility shims for local pytest runs --------------------- #
# Production runs on PostgreSQL; CI uses a real Postgres service. The
# in-memory SQLite fixture below lets developers iterate without Docker,
# but Postgres-only types and server defaults don't compile to SQLite DDL.
# Register dialect-scoped compilers so types degrade gracefully on SQLite
# without touching the ORM models. PG-only defaults are stripped at
# table-create time inside the fixture, and Python-side adapters JSON-encode
# ARRAY values and stringify UUIDs.


@compiles(JSONB, "sqlite")  # type: ignore[no-redef]
def _compile_jsonb_sqlite(element, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(ARRAY, "sqlite")  # type: ignore[no-redef]
def _compile_array_sqlite(element, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(UUID, "sqlite")  # type: ignore[no-redef]
def _compile_uuid_sqlite(element, compiler, **kw):  # noqa: ARG001
    return "VARCHAR(36)"


@compiles(TIMESTAMP, "sqlite")  # type: ignore[no-redef]
def _compile_timestamp_sqlite(element, compiler, **kw):  # noqa: ARG001
    return "TIMESTAMP"


def _patch_pg_types_for_sqlite() -> None:
    """Install bind/result processors so ARRAY and JSONB round-trip via SQLite.

    Without this, SQLite chokes on Python ``list`` / ``dict`` parameters
    (it only knows scalars). We piggy-back on JSON encoding for both.
    """

    def _array_bind(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name != "sqlite":
            return super(ARRAY, self).bind_processor(dialect)

        def process(value):
            if value is None:
                return None
            return _json.dumps(list(value))

        return process

    def _array_result(self, dialect, coltype):  # type: ignore[no-untyped-def]
        if dialect.name != "sqlite":
            return super(ARRAY, self).result_processor(dialect, coltype)

        def process(value):
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return list(value)
            return _json.loads(value)

        return process

    def _jsonb_bind(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name != "sqlite":
            return super(JSONB, self).bind_processor(dialect)

        def process(value):
            if value is None:
                return None
            return _json.dumps(value)

        return process

    def _jsonb_result(self, dialect, coltype):  # type: ignore[no-untyped-def]
        if dialect.name != "sqlite":
            return super(JSONB, self).result_processor(dialect, coltype)

        def process(value):
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return value
            return _json.loads(value)

        return process

    def _uuid_bind(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name != "sqlite":
            return super(UUID, self).bind_processor(dialect)

        def process(value):
            if value is None:
                return None
            return str(value)

        return process

    def _uuid_result(self, dialect, coltype):  # type: ignore[no-untyped-def]
        if dialect.name != "sqlite":
            return super(UUID, self).result_processor(dialect, coltype)

        def process(value):
            if value is None:
                return None
            if isinstance(value, _uuid.UUID):
                return value
            try:
                return _uuid.UUID(str(value))
            except (ValueError, TypeError):
                return value

        return process

    ARRAY.bind_processor = _array_bind  # type: ignore[assignment]
    ARRAY.result_processor = _array_result  # type: ignore[assignment]
    JSONB.bind_processor = _jsonb_bind  # type: ignore[assignment]
    JSONB.result_processor = _jsonb_result  # type: ignore[assignment]
    UUID.bind_processor = _uuid_bind  # type: ignore[assignment]
    UUID.result_processor = _uuid_result  # type: ignore[assignment]


_patch_pg_types_for_sqlite()


from rp_server.auth import create_enrollment_token  # noqa: E402
from rp_server.database import get_db  # noqa: E402
from rp_server.main import app  # noqa: E402
from rp_server.models import Base, Enrollment  # noqa: E402


def _install_sqlite_python_defaults() -> None:
    """Replace PG-only server-side defaults with Python equivalents.

    The production ORM models use server defaults like ``gen_random_uuid()``
    and ``now()`` that SQLite can't evaluate. Set Python-side ``default=``
    on the column so SQLAlchemy fills them in before the INSERT, and clear
    the PG-only ``server_default`` so ``create_all`` succeeds on SQLite.
    """
    for table in Base.metadata.tables.values():
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            txt = str(getattr(sd, "arg", "")).lower()
            if "gen_random_uuid" in txt:
                col.server_default = None
                col.default = ColumnDefault(lambda: _uuid.uuid4())
            elif "now()" in txt:
                col.server_default = None
                col.default = ColumnDefault(lambda: datetime.now(timezone.utc))
            elif "::jsonb" in txt and "{}" in txt:
                col.server_default = None
                col.default = ColumnDefault(lambda: {})
            elif "array[" in txt:
                col.server_default = None
                col.default = ColumnDefault(lambda: [])


_install_sqlite_python_defaults()


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Set up minimal test environment variables."""
    os.environ["POSTGRES_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
    os.environ["JWT_SECRET"] = "test-secret-key-minimum-32-characters-long"
    os.environ["SERVER_URL"] = "http://test"
    os.environ["TAILSCALE_API_KEY"] = ""  # Empty by default for tests
    yield
    # Cleanup
    for key in ["POSTGRES_URL", "JWT_SECRET", "SERVER_URL", "TAILSCALE_API_KEY"]:
        os.environ.pop(key, None)


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

    # PG-only server defaults (gen_random_uuid, now(), etc) have already
    # been replaced with Python-side ColumnDefaults at module import time
    # (see _install_sqlite_python_defaults above).
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
