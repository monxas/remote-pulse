"""Pytest fixtures for async testing."""

import asyncio
import json as _json
import os
import uuid as _uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import ColumnDefault
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool

# --- SQLite compatibility shims for local pytest runs --------------------- #
# Production runs on PostgreSQL; CI uses a real Postgres service. The
# in-memory SQLite fixture below lets developers iterate without Docker,
# but Postgres-only types and server defaults don't compile to SQLite DDL.
# Register dialect-scoped compilers so types degrade gracefully on SQLite
# without touching the ORM models. PG-only defaults are stripped at
# table-create time inside the fixture, and Python-side adapters JSON-encode
# ARRAY values and stringify UUIDs.


@compiles(JSONB, "sqlite")  # type: ignore[no-redef]
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(ARRAY, "sqlite")  # type: ignore[no-redef]
def _compile_array_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")  # type: ignore[no-redef]
def _compile_uuid_sqlite(element, compiler, **kw):
    return "VARCHAR(36)"


@compiles(TIMESTAMP, "sqlite")  # type: ignore[no-redef]
def _compile_timestamp_sqlite(element, compiler, **kw):
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
from rp_server.models import Base, Enrollment, User  # noqa: E402


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
                col.default = ColumnDefault(lambda: datetime.now(UTC))
            elif "::jsonb" in txt and "{}" in txt:
                col.server_default = None
                col.default = ColumnDefault(dict)
            elif "::jsonb" in txt and "[]" in txt:
                col.server_default = None
                col.default = ColumnDefault(list)
            elif "array[" in txt:
                col.server_default = None
                col.default = ColumnDefault(list)


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

    Foreign-key enforcement is enabled per-connection via ``PRAGMA
    foreign_keys=ON`` so ``ON DELETE CASCADE`` clauses in the models
    actually fire in tests — without it SQLite silently leaves orphans
    and tests that assert cascade behaviour would pass for the wrong
    reason.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    from sqlalchemy import event as _sa_event

    @_sa_event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fks(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

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
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    """Session on the real, alembic-migrated Postgres that CI provisions.

    For the handful of tests marked ``postgres``: they assert things only a real
    Postgres has -- migration-seeded rows, TRUNCATE triggers, ARRAY semantics --
    and previously took the SQLite ``test_db`` fixture instead, which is why
    test_postgres_immutability.py failed on "near TRUNCATE: syntax error"
    despite being labelled "Postgres-real".

    Uses ``POSTGRES_URL`` from the environment (the workflow points it at the
    service container). Everything runs inside a transaction that is rolled back
    afterwards, so the shared database is left exactly as alembic made it.
    """
    url = os.environ.get("POSTGRES_URL", "")
    if "postgresql" not in url:
        pytest.fail(
            "pg_session requires POSTGRES_URL to point at a real Postgres; "
            f"got {url!r}. These tests are selected with `-m postgres`."
        )

    engine = create_async_engine(url, poolclass=NullPool)
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_signing_key(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the Ed25519 server signing key out of /etc/rp.

    ``ServerSigningKey.load_or_generate()`` defaults to /etc/rp and the
    enroll / heartbeat / keys / commands routers all call it through a lazy
    module-level singleton, so simply touching those endpoints from a test
    tries to generate a real key under /etc. Unprivileged runners get
    PermissionError (12 tests), and a privileged one would be worse: the
    suite would write to a real system path.

    test_dash_phase2, test_user_permissions, test_short_code_enrollment and
    others each grew their own local copy of this; hoisted here so the whole
    suite is hermetic. monkeypatch restores the singletons after each test.
    """
    from rp_server.routers import commands as _commands
    from rp_server.routers import enroll as _enroll
    from rp_server.routers import keys as _keys
    from rp_server.signing import ServerSigningKey

    key = ServerSigningKey.load_or_generate(tmp_path / "signing")
    monkeypatch.setattr(_commands, "_signing_key", key, raising=False)
    monkeypatch.setattr(_enroll, "_server_signing_key", key, raising=False)
    monkeypatch.setattr(_keys, "_server_signing_key", key, raising=False)


@pytest.fixture
async def as_admin(test_db: AsyncSession) -> AsyncGenerator[User, None]:
    """Authenticate the test client as a real admin row.

    Opt-in on purpose -- it is NOT autouse, so the modules that assert on
    unauthenticated behaviour keep asserting it. `require_admin` and
    `require_operator_or_admin` both resolve through `current_user`, so
    overriding that one dependency covers them.
    """
    from rp_server.deps import current_user

    user = User(
        pocketid_sub=f"test-admin-{_uuid.uuid4().hex[:8]}",
        email=f"admin-{_uuid.uuid4().hex[:6]}@test.local",
        name="Test Admin",
        role="admin",
        accessible_groups=[],
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)

    async def _current_user() -> User:
        return user

    app.dependency_overrides[current_user] = _current_user
    yield user
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
def as_tailnet() -> Generator[None, None, None]:
    """Present the request as coming from a verified tailnet identity.

    routers/keys.py gates on `tailscale_identity` / `tailscale_identity_optional`
    rather than on `current_user`.
    """
    from rp_server.deps import (
        TailscaleIdentity,
        tailscale_identity,
        tailscale_identity_optional,
    )

    identity = TailscaleIdentity(
        login="test@monxas.casa",
        name="Test Tailnet User",
        node_id="test-node",
    )

    async def _identity() -> TailscaleIdentity:
        return identity

    app.dependency_overrides[tailscale_identity] = _identity
    app.dependency_overrides[tailscale_identity_optional] = _identity
    yield
    app.dependency_overrides.pop(tailscale_identity, None)
    app.dependency_overrides.pop(tailscale_identity_optional, None)


@pytest.fixture
async def db_session(test_db: AsyncSession) -> AsyncSession:
    """Alias of ``test_db``.

    Seven test modules (approvals, canary, keys_router, metrics,
    metrics_endpoint, agent_commands, users_auth) ask for a ``db_session``
    fixture that only ever existed module-locally inside test_models_f4.py, so
    pytest reported "fixture 'db_session' not found" and errored out 52 tests at
    setup. They use it exactly like ``test_db``, so it is exposed here under
    both names rather than renamed across eight files.
    """
    return test_db


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
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_uses=1,
        used_count=0,
    )

    test_db.add(enrollment)
    await test_db.commit()

    return token
