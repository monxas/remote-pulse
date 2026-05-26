"""Tests for ``/v1/dash/audit/export`` — CSV / JSON download for compliance."""

from __future__ import annotations

import csv
import io
import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.routers import commands as commands_router
from rp_server.routers import dash_commands as dash_commands_router

from test_dash_phase2 import (
    _clear_user_override,
    _make_command,
    _make_host,
    _make_user,
    _override_user,
)


@pytest.fixture(autouse=True)
def _patch_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeKey:
        def sign_command(self, *a, **kw):
            return "sig-stub"

        def public_key_pem(self) -> bytes:
            return b"-----BEGIN PUBLIC KEY-----\nstub\n-----END PUBLIC KEY-----\n"

    monkeypatch.setattr(commands_router, "get_signing_key", lambda: _FakeKey())
    monkeypatch.setattr(dash_commands_router, "get_signing_key", lambda: _FakeKey())


@pytest.mark.asyncio
async def test_export_csv_basic(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="csv-host", group="prod")
    await _make_command(test_db, host=host, issued_by="alice@x")
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit/export?format=csv")
    finally:
        _clear_user_override()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment; filename=")
    assert ".csv" in cd

    # Parse the CSV and verify the header + at least one row.
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    assert rows[0] == [
        "timestamp",
        "actor",
        "action",
        "resource_type",
        "resource_id",
        "target_label",
        "payload",
    ]
    assert len(rows) >= 2  # header + ≥1 data row
    # Find a command.issued row and verify shape.
    data_rows = rows[1:]
    issued = [r for r in data_rows if r[2] == "command.issued"]
    assert issued, "expected at least one command.issued row"
    payload = json.loads(issued[0][6])  # JSON-encoded column
    assert isinstance(payload, dict)


@pytest.mark.asyncio
async def test_export_json_basic(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="json-host", group="prod")
    await _make_command(test_db, host=host)
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit/export?format=json")
    finally:
        _clear_user_override()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment; filename=")
    assert ".json" in cd
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    sample = body[0]
    for key in ("id", "ts", "actor", "action", "target_type", "target_id"):
        assert key in sample


@pytest.mark.asyncio
async def test_export_default_format_is_csv(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="def-host", group="prod")
    await _make_command(test_db, host=host)
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit/export")
    finally:
        _clear_user_override()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")


@pytest.mark.asyncio
async def test_export_filters_apply(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="filt-host", group="prod")
    await _make_command(test_db, host=host, issued_by="alice@x")
    await _make_command(test_db, host=host, issued_by="bob@x")
    _override_user(admin)
    try:
        resp = await client.get(
            "/v1/dash/audit/export?format=json&action=command.issued&actor=alice@x"
        )
    finally:
        _clear_user_override()
    body = resp.json()
    assert all(e["action"] == "command.issued" for e in body)
    assert all(e["actor"] == "alice@x" for e in body)
    assert len(body) == 1


@pytest.mark.asyncio
async def test_export_unknown_format_is_422(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit/export?format=xml")
    finally:
        _clear_user_override()
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_export_non_admin_is_forbidden(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    viewer = await _make_user(test_db, role="viewer", groups=["prod"])
    _override_user(viewer)
    try:
        resp = await client.get("/v1/dash/audit/export?format=csv")
    finally:
        _clear_user_override()
    # require_admin returns 403 for non-admin users.
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_export_action_prefix(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="ap-host", group="prod")
    await _make_command(test_db, host=host)  # command.issued
    _override_user(admin)
    try:
        # No settings events seeded, but command.* events must still match.
        resp = await client.get(
            "/v1/dash/audit/export?format=json&action_prefix=command."
        )
    finally:
        _clear_user_override()
    body = resp.json()
    assert all(e["action"].startswith("command.") for e in body)
    assert len(body) >= 1
