"""CLI integration tests for `rp install-screen`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from rp.commands import install_screen as cmd_mod
from rp.commands.install_screen import install_screen as main
from rp.installers import InstallResult


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_install_screen_help(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0, result.output
    assert "rustdesk" in result.output.lower()
    assert "sunshine" in result.output.lower()
    assert "vnc" in result.output.lower()
    assert "status" in result.output.lower()


def test_install_screen_status_prints_table(runner, monkeypatch):
    async def fake_detect(_self):
        return False

    async def fake_version(_self):
        return None

    monkeypatch.setattr(
        "rp.installers.rustdesk.RustDeskInstaller.detect_installed", fake_detect
    )
    monkeypatch.setattr(
        "rp.installers.rustdesk.RustDeskInstaller.detect_version", fake_version
    )
    monkeypatch.setattr(
        "rp.installers.sunshine.SunshineInstaller.detect_installed", fake_detect
    )
    monkeypatch.setattr(
        "rp.installers.sunshine.SunshineInstaller.detect_version", fake_version
    )
    monkeypatch.setattr("rp.installers.vnc.VNCInstaller.detect_installed", fake_detect)

    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0, result.output
    assert "RustDesk" in result.output
    assert "Sunshine" in result.output
    assert "TigerVNC" in result.output


def test_install_screen_rustdesk_force_idempotent(runner, monkeypatch):
    """`rp install-screen rustdesk --force` runs install + configure + skips report."""

    install_mock = AsyncMock(
        return_value=InstallResult(
            tool="rustdesk",
            installed=True,
            version="1.2.3",
            method="brew-cask",
        )
    )
    configure_mock = AsyncMock(
        return_value={
            "password": "x" * 32,
            "id_server": "direct",
            "relay_server": "none",
            "direct_ip": "0.0.0.0",
            "config_path": "/etc/rp/rustdesk.toml",
        }
    )

    monkeypatch.setattr(cmd_mod.RustDeskInstaller, "install", install_mock)
    monkeypatch.setattr(
        cmd_mod.RustDeskInstaller, "configure_direct_ip", configure_mock
    )

    result = runner.invoke(
        main,
        [
            "rustdesk",
            "--force",
            "--skip-server-report",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "rustdesk 1.2.3 installed" in result.output
    assert "Direct IP configured" in result.output

    install_mock.assert_called_once()
    configure_mock.assert_called_once()


def test_install_screen_sunshine_blocks_non_windows(runner, monkeypatch):
    monkeypatch.setattr(cmd_mod, "get_os", lambda: "macos")
    result = runner.invoke(main, ["sunshine"])
    assert result.exit_code != 0
    assert "Windows" in result.output


def test_install_screen_vnc_blocks_non_linux(runner, monkeypatch):
    monkeypatch.setattr(cmd_mod, "get_os", lambda: "macos")
    result = runner.invoke(main, ["vnc"])
    assert result.exit_code != 0
    assert "Linux" in result.output


def test_install_screen_rustdesk_surface_installer_error(runner, monkeypatch):
    from rp.installers import InstallerError as IE

    async def boom(*args, **kwargs):
        raise IE("brew install rustdesk failed: cask not found")

    monkeypatch.setattr(cmd_mod.RustDeskInstaller, "install", boom)

    result = runner.invoke(
        main,
        [
            "rustdesk",
            "--skip-server-report",
        ],
    )
    assert result.exit_code != 0
    assert "brew install rustdesk failed" in result.output
