"""Test audit log immutability (Postgres trigger enforcement).

F8-SECURITY: Commands table is append-only, enforced by Postgres BEFORE UPDATE/DELETE triggers.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from rp_server.models import Command


@pytest.mark.asyncio
async def test_command_update_raises_immutable_error(test_db, monkeypatch):
    """Verify Postgres trigger blocks UPDATE on commands table.

    SQLite skip: SQLite does not support RAISE() in triggers same way as Postgres.
    """
    if "sqlite" in str(test_db.bind.url):
        pytest.skip("Postgres-only test (trigger enforcement)")

    # Insert a command
    cmd = Command(
        host_id=1,
        command_type="exec_shell",
        payload={"command": "echo test"},
        status="pending",
        server_signature="dummy_sig",
        server_pubkey="dummy_pubkey",
    )
    test_db.add(cmd)
    await test_db.commit()
    await test_db.refresh(cmd)

    # Attempt UPDATE
    cmd.stdout = "tampered"
    with pytest.raises((IntegrityError, ProgrammingError), match="append-only|immutable"):
        await test_db.commit()


@pytest.mark.asyncio
async def test_command_delete_raises_immutable_error(test_db):
    """Verify Postgres trigger blocks DELETE on commands table."""
    if "sqlite" in str(test_db.bind.url):
        pytest.skip("Postgres-only test (trigger enforcement)")

    # Insert a command
    cmd = Command(
        host_id=2,
        command_type="exec_shell",
        payload={"command": "echo test"},
        status="pending",
        server_signature="dummy_sig",
        server_pubkey="dummy_pubkey",
    )
    test_db.add(cmd)
    await test_db.commit()
    await test_db.refresh(cmd)

    # Attempt DELETE
    await test_db.delete(cmd)
    with pytest.raises((IntegrityError, ProgrammingError), match="append-only|immutable"):
        await test_db.commit()


@pytest.mark.asyncio
async def test_truncate_blocked(test_db):
    """TRUNCATE should also fail (trigger is BEFORE TRUNCATE)."""
    if "sqlite" in str(test_db.bind.url):
        pytest.skip("Postgres-only test (TRUNCATE trigger)")

    # Insert a command
    cmd = Command(
        host_id=3,
        command_type="exec_shell",
        payload={"command": "echo test"},
        status="pending",
        server_signature="dummy_sig",
        server_pubkey="dummy_pubkey",
    )
    test_db.add(cmd)
    await test_db.commit()

    # Attempt TRUNCATE
    with pytest.raises((IntegrityError, ProgrammingError), match="append-only|immutable"):
        await test_db.execute(text("TRUNCATE TABLE commands"))
        await test_db.commit()
