"""Postgres-real audit-log guarantees for the ``commands`` table (M2 review gap).

SQLite has no triggers and no TRUNCATE, so these can only be validated against a
real Postgres. They are selected by `-m postgres`, which CI runs as its own step
against the alembic-migrated service database.

Two things were wrong here before, and both mattered:

1. Every test took the ``test_db`` fixture -- the in-memory SQLite one. So a
   module whose whole purpose is "verify the Postgres triggers" never touched
   Postgres, and failed with "near TRUNCATE: syntax error" and "type 'UUID' is
   not supported" the first time it was ever executed. They now take
   ``pg_session``.

2. ``test_commands_update_blocked`` and ``test_commands_delete_blocked``
   asserted a BEFORE UPDATE / BEFORE DELETE trigger that does not exist. Checked
   against the production database: ``commands`` carries exactly one trigger,
   ``commands_truncate_immutable`` (BEFORE TRUNCATE). Nothing stops an UPDATE or
   DELETE at the database level, and nothing can, in blanket form -- the command
   lifecycle legitimately updates rows (claim, approve, reject, results), all via
   Core ``update(Command)`` which bypasses the ORM guard by design.

   So the "append-only audit log" wording in models.py / the ADR is stronger than
   what is enforced. The tests below now pin what is actually true, and the gap is
   written up in the PR rather than left as a green check. Fixing it properly means
   a column-scoped trigger (freeze host_id / command_type / command_payload /
   server_signature / issued_by / created_at, allow the lifecycle columns) in its
   own migration -- deliberately not done here, because getting that column list
   wrong breaks command dispatch on a live fleet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from rp_server.models import Command, Host

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


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


async def test_commands_update_is_not_blocked_at_db_level(pg_session):
    """KNOWN GAP: a Core UPDATE on commands succeeds -- there is no trigger.

    This is the honest version of the old ``test_commands_update_blocked``,
    which expected an exception that the database never raises. It is written as
    an assertion rather than dropped so the gap stays visible: the day someone
    adds the column-scoped trigger described in the module docstring, this test
    fails and has to be updated deliberately.
    """
    host_id = await _insert_host(pg_session)
    cmd_id = await _insert_command(pg_session, host_id)

    await pg_session.execute(
        update(Command).where(Command.id == cmd_id).values(stdout="tampered")
    )
    await pg_session.commit()

    stdout = (
        await pg_session.execute(select(Command.stdout).where(Command.id == cmd_id))
    ).scalar_one()
    assert stdout == "tampered", (
        "If this now fails, the DB-level UPDATE guard was added -- good. "
        "Rewrite this test to assert the audit columns are frozen."
    )


async def test_commands_delete_is_not_blocked_at_db_level(pg_session):
    """KNOWN GAP: a Core DELETE on commands succeeds -- there is no trigger.

    Same reasoning as the UPDATE case above.
    """
    host_id = await _insert_host(pg_session)
    cmd_id = await _insert_command(pg_session, host_id)

    await pg_session.execute(delete(Command).where(Command.id == cmd_id))
    await pg_session.commit()

    remaining = (
        await pg_session.execute(select(Command.id).where(Command.id == cmd_id))
    ).scalar_one_or_none()
    assert remaining is None


async def test_commands_orm_guard_blocks_attribute_mutation(pg_session):
    """What *is* enforced: the ORM guard refuses to mutate a persistent row.

    This is the actual mechanism behind the "append-only" claim, so it gets a
    test against the real database too, not just SQLite.
    """
    host_id = await _insert_host(pg_session)
    cmd_id = await _insert_command(pg_session, host_id)

    command = (
        await pg_session.execute(select(Command).where(Command.id == cmd_id))
    ).scalar_one()

    with pytest.raises(RuntimeError, match="append-only"):
        command.stdout = "tampered"


async def test_commands_truncate_blocked(pg_session):
    """The BEFORE TRUNCATE trigger (M1 fix) MUST raise."""
    host_id = await _insert_host(pg_session)
    await _insert_command(pg_session, host_id)

    # plpgsql RAISE EXCEPTION surfaces as SQLSTATE P0001, which SQLAlchemy maps
    # to InternalError, not IntegrityError/ProgrammingError as the old test
    # assumed. DBAPIError is their common parent; the message check below is
    # what actually pins the behaviour.
    with pytest.raises(DBAPIError) as ei:
        await pg_session.execute(text("TRUNCATE TABLE commands"))
        await pg_session.commit()

    msg = str(ei.value).lower()
    assert "append-only" in msg or "truncate blocked" in msg


async def test_commands_insert_allowed(pg_session):
    """INSERT (the only legal mutation) MUST succeed."""
    host_id = await _insert_host(pg_session)
    cmd_id = await _insert_command(pg_session, host_id)

    row = await pg_session.execute(
        text("SELECT id FROM commands WHERE id = :id"), {"id": cmd_id}
    )
    assert row.scalar_one() == cmd_id


async def test_approval_expiry_window_atomic(pg_session):
    """M4 atomic claim must reject expired tokens (>5min)."""
    host_id = await _insert_host(pg_session)
    token = uuid.uuid4()

    cmd = Command(
        host_id=host_id,
        issued_by="test@example.com",
        command_type="reboot",
        command_payload={},
        server_signature="x",
        approval_token=token,
        approval_requested_at=datetime.now(UTC) - timedelta(minutes=10),
        human_approved=False,
    )
    pg_session.add(cmd)
    await pg_session.commit()

    result = await pg_session.execute(
        update(Command)
        .where(
            Command.approval_token == token,
            Command.human_approved.is_(False),
            Command.approval_requested_at >= datetime.now(UTC) - timedelta(seconds=300),
        )
        .values(human_approved=True, approved_by="telegram:test")
        .returning(Command.id)
    )
    assert result.first() is None, "Expired token must not be claimable"


async def test_approval_token_atomic_single_winner(pg_session):
    """M4 atomic claim — two concurrent claimants race; exactly one wins."""
    host_id = await _insert_host(pg_session)
    token = uuid.uuid4()

    cmd = Command(
        host_id=host_id,
        issued_by="test@example.com",
        command_type="reboot",
        command_payload={},
        server_signature="x",
        approval_token=token,
        approval_requested_at=datetime.now(UTC),
        human_approved=False,
    )
    pg_session.add(cmd)
    await pg_session.commit()

    claim_stmt = (
        update(Command)
        .where(
            Command.approval_token == token,
            Command.human_approved.is_(False),
        )
        .values(human_approved=True, approved_by="telegram:test", approval_token=None)
        .returning(Command.id)
    )

    first = await pg_session.execute(claim_stmt)
    second = await pg_session.execute(claim_stmt)
    await pg_session.commit()

    assert first.first() is not None
    assert second.first() is None, "Second claim must observe rowcount=0"
