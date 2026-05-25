"""Tests for remote command runner stub (F4-4 integration point)."""

import pytest

from rp.commands.runner import execute_remote_command, RemoteCommand


@pytest.mark.asyncio
async def test_runner_denies_based_on_policy(tmp_path):
    """Runner should deny commands based on local policy."""
    cmd = RemoteCommand(
        id="test-cmd-1",
        command_type="exec_shell",
        payload={},
        target_group="prod",
        issued_by="test-user",
        server_signature="fake-sig",
    )

    result = await execute_remote_command(cmd)

    assert result.ack is False
    assert "local_policy_deny" in result.rejected_reason
    assert "allow-remote-exec" in result.rejected_reason


@pytest.mark.asyncio
async def test_runner_requires_approval_for_pkg_install(tmp_path):
    """Runner should require approval for pkg_install on prod."""
    cmd = RemoteCommand(
        id="test-cmd-2",
        command_type="pkg_install",
        payload={"name": "nginx"},
        target_group="prod",
        issued_by="test-user",
        server_signature="fake-sig",
    )

    # Should return rejection because Telegram approval not implemented
    result = await execute_remote_command(cmd)
    assert result.ack is False
    assert "telegram_approval_not_implemented" in result.rejected_reason


@pytest.mark.asyncio
async def test_runner_raises_not_implemented_for_execution():
    """Runner should raise NotImplementedError for allowed commands (F4-4)."""
    cmd = RemoteCommand(
        id="test-cmd-3",
        command_type="exec_shell",
        payload={},
        target_group="family",  # family allows exec
        issued_by="test-user",
        server_signature="fake-sig",
    )

    # Should raise NotImplementedError when trying to execute
    with pytest.raises(NotImplementedError, match="Command execution.*F4-4"):
        await execute_remote_command(cmd)


@pytest.mark.asyncio
async def test_runner_screen_open_not_implemented():
    """Runner should allow screen_open but execution not implemented."""
    cmd = RemoteCommand(
        id="test-cmd-4",
        command_type="screen_open",
        payload={"protocol": "rustdesk"},
        target_group="prod",
        issued_by="test-user",
        server_signature="fake-sig",
    )

    # screen_open is always allowed, so should reach execution stub
    with pytest.raises(NotImplementedError, match="F4-4"):
        await execute_remote_command(cmd)
