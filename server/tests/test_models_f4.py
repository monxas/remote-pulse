"""F4 schema smoke tests - groups, ssh_keys, commands, agent_versions."""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from rp_server.models import AgentVersion, Base, Command, Group, Host, SSHKey

# Postgres-only tests (ARRAY type, triggers)
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_session():
    """Create test database session with F4 schema."""
    # Use in-memory SQLite for simple tests, but ARRAY types require postgres
    # In real CI, this should point to test postgres instance
    engine = create_async_engine(
        "postgresql+asyncpg://test:test@localhost/test_rp",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()


async def test_group_create_and_query(db_session: AsyncSession):
    """Test creating groups with ARRAY access_users."""
    # Create test group
    group = Group(
        name="test-group",
        description="Test group for F4",
        access_users=["user1@example.com", "user2@example.com"],
        auto_distribute_keys=True,
    )
    db_session.add(group)
    await db_session.commit()

    # Query back
    result = await db_session.execute(select(Group).where(Group.name == "test-group"))
    fetched = result.scalar_one()

    assert fetched.name == "test-group"
    assert fetched.description == "Test group for F4"
    assert fetched.access_users == ["user1@example.com", "user2@example.com"]
    assert fetched.auto_distribute_keys is True
    assert isinstance(fetched.created_at, datetime)


async def test_ssh_key_linked_to_host(db_session: AsyncSession):
    """Test SSH key creation with FK to host."""
    # Create test host first
    host = Host(
        hostname="test-host",
        os="linux",
        arch="x86_64",
        distro="debian-12",
        agent_version="0.1.0",
    )
    db_session.add(host)
    await db_session.commit()

    # Create SSH key
    ssh_key = SSHKey(
        host_id=host.id,
        user_name="root",
        pubkey="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAbCdEfGhIjKlMnOpQrStUvWxYz test@example",
        fingerprint="SHA256:abcdefghijklmnopqrstuvwxyz0123456789ABC",
        algorithm="ed25519",
    )
    db_session.add(ssh_key)
    await db_session.commit()

    # Query by host_id
    result = await db_session.execute(select(SSHKey).where(SSHKey.host_id == host.id))
    fetched = result.scalar_one()

    assert fetched.host_id == host.id
    assert fetched.user_name == "root"
    assert fetched.algorithm == "ed25519"
    assert fetched.revoked_at is None


async def test_ssh_key_cascade_delete(db_session: AsyncSession):
    """Test SSH key cascade deletes when host is deleted."""
    # Create host and key
    host = Host(
        hostname="cascade-test",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
    )
    db_session.add(host)
    await db_session.commit()

    ssh_key = SSHKey(
        host_id=host.id,
        pubkey="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICascadeTest test",
        fingerprint="SHA256:cascadeTestFingerprint1234567890ABCD",
        algorithm="ed25519",
    )
    db_session.add(ssh_key)
    await db_session.commit()

    key_id = ssh_key.id

    # Delete host
    await db_session.delete(host)
    await db_session.commit()

    # Verify key is gone
    result = await db_session.execute(select(SSHKey).where(SSHKey.id == key_id))
    assert result.scalar_one_or_none() is None


async def test_command_immutable_via_trigger(db_session: AsyncSession):
    """Test commands table is immutable (UPDATE raises exception)."""
    # Create host
    host = Host(
        hostname="cmd-test",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
    )
    db_session.add(host)
    await db_session.commit()

    # Create command
    command = Command(
        host_id=host.id,
        issued_by="test-user",
        command_type="exec_shell",
        command_payload={"cmd": "echo test"},
        server_signature="sig123",
    )
    db_session.add(command)
    await db_session.commit()

    # Try to update (should raise)
    command.exit_code = 0
    with pytest.raises(Exception, match="append-only"):
        await db_session.commit()


async def test_command_immutable_via_model(db_session: AsyncSession):
    """Test Command.__setattr__ prevents modification after commit."""
    # Create host
    host = Host(
        hostname="model-test",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
    )
    db_session.add(host)
    await db_session.commit()

    # Create command and commit
    command = Command(
        host_id=host.id,
        issued_by="test-user",
        command_type="exec_shell",
        command_payload={"cmd": "echo model"},
        server_signature="sig456",
    )
    db_session.add(command)
    await db_session.commit()

    # Detach from session and try to modify
    db_session.expunge(command)

    with pytest.raises(RuntimeError, match="Cannot modify Command after commit"):
        command.exit_code = 1


async def test_host_group_fk_constraint(db_session: AsyncSession):
    """Test host.group_name FK to groups.name."""
    # Create group first
    group = Group(name="fk-test-group", description="FK test")
    db_session.add(group)
    await db_session.commit()

    # Create host with valid group
    host = Host(
        hostname="fk-host",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
        group_name="fk-test-group",
    )
    db_session.add(host)
    await db_session.commit()

    # Query back
    result = await db_session.execute(select(Host).where(Host.hostname == "fk-host"))
    fetched = result.scalar_one()
    assert fetched.group_name == "fk-test-group"


async def test_agent_version_tracking(db_session: AsyncSession):
    """Test agent_versions table."""
    # Create host
    host = Host(
        hostname="version-test",
        os="linux",
        arch="x86_64",
        agent_version="0.5.2",
    )
    db_session.add(host)
    await db_session.commit()

    # Create agent version record
    agent_version = AgentVersion(
        host_id=host.id,
        agent_version="0.5.2",
        api_compat_min="0.5.0",
        api_compat_max="0.6.0",
    )
    db_session.add(agent_version)
    await db_session.commit()

    # Query back
    result = await db_session.execute(select(AgentVersion).where(AgentVersion.host_id == host.id))
    fetched = result.scalar_one()

    assert fetched.agent_version == "0.5.2"
    assert fetched.api_compat_min == "0.5.0"
    assert fetched.api_compat_max == "0.6.0"
    assert isinstance(fetched.last_check, datetime)


async def test_default_groups_seeded(db_session: AsyncSession):
    """Test that migration 003 seeds default groups."""
    # Query for seeded groups
    result = await db_session.execute(
        select(Group).where(Group.name.in_(["default", "prod", "family", "iarq"]))
    )
    groups = result.scalars().all()

    group_names = {g.name for g in groups}
    assert "default" in group_names
    assert "prod" in group_names
    assert "family" in group_names
    assert "iarq" in group_names

    # Verify access_users ARRAY
    prod_group = next(g for g in groups if g.name == "prod")
    assert "ramon@monxas.casa" in prod_group.access_users
