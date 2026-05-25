"""Postgres-real audit-log immutability tests (M2 review gap).

SQLite has no triggers, no DDL TRUNCATE — so the immutability guarantees of
the ``commands`` table can ONLY be validated against a real Postgres. These
tests are marked ``postgres`` and are skipped automatically when the
``POSTGRES_URL`` env var is not present or is sqlite-flavoured.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError

from rp_server.models import Command, Host

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


def _postgres_available() -> bool:
    url = os.environ.get("POSTGRES_URL", "")
    return "postgresql" in url and "sqlite" not in url


pytestmark.append(
    pytest.mark.skipif(not _postgres_available(), reason="needs real Postgres in CI")
)


async def _insert_host(session) -> uuid.UUID:
    host = Host(
        hostname=f"test-host-{uuid.uuid4().hex[:8]}",
        os="linux",
        arch="x64",
        agent_version="1.0.0",
    )
    session.add(host)
    await session.commit()
    await session.refresh(host)
    return host.id


async def _insert_command(session, host_id: uuid.UUID) -> uuid.UUID:
    cmd = Command(
        host_id=host_id,
        issued_by="test@example.com",
        command_type="exec_shell",
        command_payload={"cmd": "echo hi"},
        server_signature="fake-sig-for-test",
    )
    session.add(cmd)
    await session.commit()
    await session.refresh(cmd)
    return cmd.id


async def test_commands_update_blocked(test_db):
    """The BEFORE UPDATE trigger MUST raise."""
    host_id = await _insert_host(test_db)
    cmd_id = await _insert_command(test_db, host_id)

    with pytest.raises((IntegrityError, ProgrammingError)) as ei:
        await test_db.execute(
            update(Command).where(Command.id == cmd_id).values(stdout="tampered")
        )
        await test_db.commit()

    assert "append-only" in str(ei.value).lower()


async def test_commands_delete_blocked(test_db):
    """The BEFORE DELETE trigger MUST raise."""
    host_id = await _insert_host(test_db)
    cmd_id = await _insert_command(test_db, host_id)

    with pytest.raises((IntegrityError, ProgrammingError)) as ei:
        await test_db.execute(delete(Command).where(Command.id == cmd_id))
        await test_db.commit()

    assert "append-only" in str(ei.value).lower()


async def test_commands_truncate_blocked(test_db):
    """The BEFORE TRUNCATE trigger (M1 fix) MUST raise."""
    host_id = await _insert_host(test_db)
    await _insert_command(test_db, host_id)

    with pytest.raises((IntegrityError, ProgrammingError)) as ei:
        await test_db.execute(text("TRUNCATE TABLE commands"))
        await test_db.commit()

    msg = str(ei.value).lower()
    assert "append-only" in msg or "truncate blocked" in msg


async def test_commands_insert_allowed(test_db):
    """INSERT (the only legal mutation) MUST succeed."""
    host_id = await _insert_host(test_db)
    cmd_id = await _insert_command(test_db, host_id)

    row = await test_db.execute(
        text("SELECT id FROM commands WHERE id = :id"), {"id": cmd_id}
    )
    assert row.scalar_one() == cmd_id


async def test_approval_expiry_window_atomic(test_db):
    """M4 atomic claim must reject expired tokens (>5min)."""
    host_id = await _insert_host(test_db)
    token = uuid.uuid4()

    cmd = Command(
        host_id=host_id,
        issued_by="test@example.com",
        command_type="reboot",
        command_payload={},
        server_signature="x",
        approval_token=token,
        approval_requested_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        human_approved=False,
    )
    test_db.add(cmd)
    await test_db.commit()

    result = await test_db.execute(
        update(Command)
        .where(
            Command.approval_token == token,
            Command.human_approved.is_(False),
            Command.approval_requested_at >= datetime.now(timezone.utc) - timedelta(seconds=300),
        )
        .values(human_approved=True, approved_by="telegram:test")
        .returning(Command.id)
    )
    assert result.first() is None, "Expired token must not be claimable"


async def test_approval_token_atomic_single_winner(test_db):
    """M4 atomic claim — two concurrent claimants race; exactly one wins."""
    host_id = await _insert_host(test_db)
    token = uuid.uuid4()

    cmd = Command(
        host_id=host_id,
        issued_by="test@example.com",
        command_type="reboot",
        command_payload={},
        server_signature="x",
        approval_token=token,
        approval_requested_at=datetime.now(timezone.utc),
        human_approved=False,
    )
    test_db.add(cmd)
    await test_db.commit()

    claim_stmt = (
        update(Command)
        .where(
            Command.approval_token == token,
            Command.human_approved.is_(False),
        )
        .values(human_approved=True, approved_by="telegram:test", approval_token=None)
        .returning(Command.id)
    )

    first = await test_db.execute(claim_stmt)
    second = await test_db.execute(claim_stmt)
    await test_db.commit()

    assert first.first() is not None
    assert second.first() is None, "Second claim must observe rowcount=0"
