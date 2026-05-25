"""Tests for F5 user authentication and multi-user filtering."""

import pytest
from httpx import AsyncClient

from rp_server.models import Host, User


@pytest.mark.asyncio
async def test_current_user_creates_on_first_login(client: AsyncClient, db_session):
    """Test that current_user dependency creates user on first login."""
    response = await client.get(
        "/dash",
        headers={
            "X-Forwarded-User": "test-sub-123",
            "X-Forwarded-Email": "test@example.com",
            "X-Forwarded-Preferred-Username": "Test User",
        },
    )

    # Should fail with 200 (dashboard renders) or specific error if templates missing
    # For now, just verify it doesn't 401
    assert response.status_code != 401

    # Verify user was created in DB
    from sqlalchemy import select

    stmt = select(User).where(User.email == "test@example.com")
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()

    assert user is not None
    assert user.pocketid_sub == "test-sub-123"
    assert user.email == "test@example.com"
    assert user.name == "Test User"
    assert user.role == "viewer"
    assert user.accessible_groups == []


@pytest.mark.asyncio
async def test_multi_user_filtering_admin_sees_all(client: AsyncClient, db_session):
    """Test that admin users see all hosts regardless of group."""
    # Create admin user
    admin = User(
        pocketid_sub="admin-sub",
        email="admin@example.com",
        name="Admin User",
        role="admin",
        accessible_groups=["family"],
    )
    db_session.add(admin)

    # Create hosts in different groups
    host1 = Host(
        hostname="host-family",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
        group_name="family",
    )
    host2 = Host(
        hostname="host-prod",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
        group_name="prod",
    )
    db_session.add_all([host1, host2])
    await db_session.commit()

    # Query as admin via API (using hosts list endpoint with web auth)
    from rp_server.middleware.group_filter import filter_hosts_by_user_groups
    from sqlalchemy import select

    stmt = select(Host)
    filtered_stmt = filter_hosts_by_user_groups(stmt, admin)
    result = await db_session.execute(filtered_stmt)
    hosts = result.scalars().all()

    # Admin should see both hosts
    assert len(hosts) == 2


@pytest.mark.asyncio
async def test_multi_user_filtering_viewer_sees_only_accessible(client: AsyncClient, db_session):
    """Test that viewer users only see hosts in their accessible_groups."""
    # Create viewer user with family access only
    viewer = User(
        pocketid_sub="viewer-sub",
        email="viewer@example.com",
        name="Viewer User",
        role="viewer",
        accessible_groups=["family"],
    )
    db_session.add(viewer)

    # Create hosts in different groups
    host1 = Host(
        hostname="host-family",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
        group_name="family",
    )
    host2 = Host(
        hostname="host-prod",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
        group_name="prod",
    )
    db_session.add_all([host1, host2])
    await db_session.commit()

    # Query as viewer
    from rp_server.middleware.group_filter import filter_hosts_by_user_groups
    from sqlalchemy import select

    stmt = select(Host)
    filtered_stmt = filter_hosts_by_user_groups(stmt, viewer)
    result = await db_session.execute(filtered_stmt)
    hosts = result.scalars().all()

    # Viewer should only see family host
    assert len(hosts) == 1
    assert hosts[0].hostname == "host-family"


@pytest.mark.asyncio
async def test_multi_user_filtering_no_groups_sees_nothing(client: AsyncClient, db_session):
    """Test that users with no accessible_groups see no hosts."""
    # Create user with no groups
    user = User(
        pocketid_sub="nogroup-sub",
        email="nogroup@example.com",
        name="No Group User",
        role="viewer",
        accessible_groups=[],
    )
    db_session.add(user)

    # Create host
    host = Host(
        hostname="host-family",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
        group_name="family",
    )
    db_session.add(host)
    await db_session.commit()

    # Query as no-group user
    from rp_server.middleware.group_filter import filter_hosts_by_user_groups
    from sqlalchemy import select

    stmt = select(Host)
    filtered_stmt = filter_hosts_by_user_groups(stmt, user)
    result = await db_session.execute(filtered_stmt)
    hosts = result.scalars().all()

    # Should see nothing
    assert len(hosts) == 0
