"""Tests for screen-sharing installers (F6-1, F6-2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rp.installers import (
    InstallerError,
    RustDeskInstaller,
    SunshineInstaller,
    VNCInstaller,
)
from rp.installers import base as base_mod
from rp.installers import rustdesk as rd_mod
from rp.installers import sunshine as sun_mod
from rp.installers import vnc as vnc_mod


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


@pytest.fixture
def tmp_rp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect RP_CONFIG_DIR to a temp dir for all installers."""
    monkeypatch.setattr(base_mod, "RP_CONFIG_DIR", tmp_path)
    return tmp_path


# --------------------------------------------------------------------------
# RustDeskInstaller.detect_installed
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rustdesk_detect_installed_via_which(monkeypatch):
    monkeypatch.setattr(rd_mod.shutil, "which", lambda name: "/usr/bin/rustdesk")
    installer = RustDeskInstaller()
    assert await installer.detect_installed() is True


@pytest.mark.asyncio
async def test_rustdesk_detect_not_installed(monkeypatch):
    monkeypatch.setattr(rd_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(rd_mod, "get_os", lambda: "linux")
    installer = RustDeskInstaller()
    assert await installer.detect_installed() is False


@pytest.mark.asyncio
async def test_rustdesk_detect_macos_app_bundle(monkeypatch):
    monkeypatch.setattr(rd_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(rd_mod, "get_os", lambda: "macos")

    real_exists = Path.exists

    def fake_exists(self):
        if str(self) == "/Applications/RustDesk.app":
            return True
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    installer = RustDeskInstaller()
    assert await installer.detect_installed() is True


# --------------------------------------------------------------------------
# RustDeskInstaller.install (per-OS)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rustdesk_install_skipped_when_present(monkeypatch):
    installer = RustDeskInstaller()
    monkeypatch.setattr(installer, "detect_installed", AsyncMock(return_value=True))
    monkeypatch.setattr(installer, "detect_version", AsyncMock(return_value="1.2.3"))

    result = await installer.install(force=False)
    assert result.skipped is True
    assert result.installed is True
    assert result.version == "1.2.3"


@pytest.mark.asyncio
async def test_rustdesk_install_linux_deb(monkeypatch):
    installer = RustDeskInstaller()
    monkeypatch.setattr(rd_mod, "get_os", lambda: "linux")
    monkeypatch.setattr(rd_mod, "get_distro", lambda: "debian-12")

    monkeypatch.setattr(installer, "detect_installed", AsyncMock(return_value=True))
    monkeypatch.setattr(installer, "detect_version", AsyncMock(return_value="1.2.3"))

    fake_deb = MagicMock(spec=Path)
    fake_deb.__str__ = lambda self: "/tmp/rd.deb"  # noqa: ARG005
    monkeypatch.setattr(
        installer,
        "_fetch_release_asset",
        AsyncMock(return_value={"browser_download_url": "http://x/rd.deb"}),
    )
    monkeypatch.setattr(
        installer,
        "_download_asset",
        AsyncMock(return_value=fake_deb),
    )

    calls: list[list[str]] = []

    async def fake_run(args, **kwargs):
        calls.append(list(args))
        return 0, "", ""

    monkeypatch.setattr(rd_mod, "run_subprocess", fake_run)

    result = await installer.install(force=True)
    assert result.installed is True
    assert result.method == "dpkg"
    assert calls[0][0] == "dpkg" and calls[0][1] == "-i"
    assert calls[1][0] == "apt-get"


@pytest.mark.asyncio
async def test_rustdesk_install_macos_brew(monkeypatch):
    installer = RustDeskInstaller()
    monkeypatch.setattr(rd_mod, "get_os", lambda: "macos")
    monkeypatch.setattr(rd_mod.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(
        installer,
        "detect_installed",
        AsyncMock(side_effect=[False, True]),
    )
    monkeypatch.setattr(installer, "detect_version", AsyncMock(return_value="1.2.3"))

    captured: dict[str, Any] = {}

    async def fake_run(args, **kwargs):
        captured["args"] = list(args)
        return 0, "", ""

    monkeypatch.setattr(rd_mod, "run_subprocess", fake_run)

    result = await installer.install(force=False)
    assert result.method == "brew-cask"
    assert captured["args"][:4] == ["brew", "install", "--cask", "rustdesk"]


@pytest.mark.asyncio
async def test_rustdesk_install_macos_requires_brew(monkeypatch):
    installer = RustDeskInstaller()
    monkeypatch.setattr(rd_mod, "get_os", lambda: "macos")
    monkeypatch.setattr(rd_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(installer, "detect_installed", AsyncMock(return_value=False))

    with pytest.raises(InstallerError, match="requires Homebrew"):
        await installer.install(force=False)


@pytest.mark.asyncio
async def test_rustdesk_install_windows_winget(monkeypatch):
    installer = RustDeskInstaller()
    monkeypatch.setattr(rd_mod, "get_os", lambda: "windows")
    monkeypatch.setattr(rd_mod.shutil, "which", lambda name: "C:/winget.exe")
    monkeypatch.setattr(
        installer,
        "detect_installed",
        AsyncMock(side_effect=[False, True]),
    )
    monkeypatch.setattr(installer, "detect_version", AsyncMock(return_value="1.2.3"))

    captured: dict[str, Any] = {}

    async def fake_run(args, **kwargs):
        captured["args"] = list(args)
        return 0, "", ""

    monkeypatch.setattr(rd_mod, "run_subprocess", fake_run)

    result = await installer.install(force=False)
    assert result.method == "winget"
    assert "winget" in captured["args"][0]
    assert "RustDesk.RustDesk" in captured["args"]


# --------------------------------------------------------------------------
# RustDeskInstaller.configure_direct_ip
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rustdesk_configure_direct_ip_writes_toml(tmp_rp_dir, monkeypatch):
    installer = RustDeskInstaller()
    monkeypatch.setattr(installer, "detect_version", AsyncMock(return_value="1.2.3"))

    # Skip native patcher (filesystem-touchy).
    monkeypatch.setattr(
        installer,
        "_patch_rustdesk_native_config",
        AsyncMock(return_value=None),
    )

    cfg = await installer.configure_direct_ip(tailscale_ip="100.64.0.5")

    assert len(cfg["password"]) >= 32
    assert cfg["direct_ip"] == "100.64.0.5"
    assert cfg["id_server"] == "direct"

    written = (tmp_rp_dir / "rustdesk.toml").read_text()
    assert "direct_ip_access = true" in written
    assert 'bind_addr = "100.64.0.5"' in written
    assert cfg["password"] in written


@pytest.mark.asyncio
async def test_rustdesk_configure_direct_ip_rejects_short_password(tmp_rp_dir):
    installer = RustDeskInstaller()
    with pytest.raises(InstallerError, match="at least 16 chars"):
        await installer.configure_direct_ip(password="short")


def test_rustdesk_merge_toml_preserves_unknown_keys():
    existing = 'some-other-key = "keep me"\npassword = "old"\n'
    merged = RustDeskInstaller._merge_rustdesk_toml(
        existing, password="newpw", bind_addr="100.64.0.5"
    )
    assert 'some-other-key = "keep me"' in merged
    assert 'password = "newpw"' in merged
    assert "direct-access = true" in merged
    assert 'direct-access-bind = "100.64.0.5"' in merged


# --------------------------------------------------------------------------
# SunshineInstaller
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sunshine_install_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(sun_mod, "get_os", lambda: "linux")
    installer = SunshineInstaller()
    with pytest.raises(InstallerError, match="only supported on Windows"):
        await installer.install()


@pytest.mark.asyncio
async def test_sunshine_install_requires_gpu_unless_force(monkeypatch):
    monkeypatch.setattr(sun_mod, "get_os", lambda: "windows")
    monkeypatch.setattr(SunshineInstaller, "_detect_gpu", staticmethod(lambda: False))

    installer = SunshineInstaller()
    with pytest.raises(InstallerError, match="No GPU detected"):
        await installer.install(force=False)


@pytest.mark.asyncio
async def test_sunshine_install_silent_success(monkeypatch, tmp_path):
    monkeypatch.setattr(sun_mod, "get_os", lambda: "windows")
    monkeypatch.setattr(SunshineInstaller, "_detect_gpu", staticmethod(lambda: True))

    installer = SunshineInstaller()
    monkeypatch.setattr(
        installer,
        "detect_installed",
        AsyncMock(side_effect=[False, True]),
    )
    monkeypatch.setattr(installer, "detect_version", AsyncMock(return_value="0.21.0"))

    asset = {
        "name": "sunshine-windows-installer.exe",
        "browser_download_url": "https://x/sunshine.exe",
    }
    sha = {
        "name": "sunshine-windows-installer.exe.sha256",
        "browser_download_url": "https://x/sunshine.exe.sha256",
    }
    monkeypatch.setattr(
        installer,
        "_fetch_installer_asset",
        AsyncMock(return_value=(asset, sha)),
    )

    fake_installer = tmp_path / "sun.exe"
    fake_installer.write_bytes(b"")
    monkeypatch.setattr(
        installer, "_download_asset", AsyncMock(return_value=fake_installer)
    )
    monkeypatch.setattr(installer, "_verify_sha256", AsyncMock(return_value=None))

    captured: dict[str, Any] = {}

    async def fake_run(args, **kwargs):
        captured["args"] = list(args)
        return 0, "", ""

    monkeypatch.setattr(sun_mod, "run_subprocess", fake_run)

    result = await installer.install(force=False)
    assert result.installed is True
    assert result.method == "msi-silent"
    assert captured["args"][-1] == "/S"


@pytest.mark.asyncio
async def test_sunshine_configure_writes_credentials(tmp_rp_dir, monkeypatch):
    monkeypatch.setattr(sun_mod, "get_os", lambda: "windows")
    installer = SunshineInstaller()

    monkeypatch.setattr(installer, "_open_firewall_ports", AsyncMock(return_value=None))
    monkeypatch.setattr(installer, "_enable_autostart", AsyncMock(return_value=None))

    cfg = await installer.configure(tailscale_ip="100.64.0.115")
    assert cfg["admin_url"] == "https://100.64.0.115:47990"
    assert cfg["username"] == "rp-admin"
    assert len(str(cfg["password"])) >= 32
    assert cfg["requires_manual_pairing"] is True

    written = (tmp_rp_dir / "sunshine.toml").read_text()
    assert "requires_manual_pairing = true" in written
    assert "100.64.0.115" in written


# --------------------------------------------------------------------------
# VNCInstaller
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vnc_install_rejects_non_linux(monkeypatch):
    monkeypatch.setattr(vnc_mod, "get_os", lambda: "macos")
    installer = VNCInstaller()
    with pytest.raises(InstallerError, match="only supported on Linux"):
        await installer.install()


@pytest.mark.asyncio
async def test_vnc_install_requires_x11(monkeypatch):
    monkeypatch.setattr(vnc_mod, "get_os", lambda: "linux")
    monkeypatch.setattr(VNCInstaller, "_has_x11", staticmethod(lambda: False))
    installer = VNCInstaller()
    with pytest.raises(InstallerError, match="No X11 server"):
        await installer.install()


@pytest.mark.asyncio
async def test_vnc_install_debian_apt(monkeypatch):
    monkeypatch.setattr(vnc_mod, "get_os", lambda: "linux")
    monkeypatch.setattr(vnc_mod, "get_distro", lambda: "ubuntu-24.04")
    monkeypatch.setattr(VNCInstaller, "_has_x11", staticmethod(lambda: True))

    installer = VNCInstaller()
    monkeypatch.setattr(
        installer,
        "detect_installed",
        AsyncMock(side_effect=[False, True]),
    )

    calls: list[list[str]] = []

    async def fake_run(args, **kwargs):
        calls.append(list(args))
        return 0, "", ""

    monkeypatch.setattr(vnc_mod, "run_subprocess", fake_run)

    result = await installer.install(force=False)
    assert result.method == "apt"
    assert calls[0][:2] == ["apt-get", "update"]
    assert "tigervnc-standalone-server" in calls[1]


@pytest.mark.asyncio
async def test_vnc_configure_writes_config(tmp_rp_dir, monkeypatch):
    monkeypatch.setattr(vnc_mod, "get_os", lambda: "linux")
    installer = VNCInstaller()

    cfg = await installer.configure(tailscale_ip="100.64.0.10", port=5901)
    assert cfg["port"] == 5901
    assert cfg["bind_addr"] == "100.64.0.10"
    assert len(str(cfg["password"])) >= 20

    body = (tmp_rp_dir / "vnc.toml").read_text()
    assert "port = 5901" in body
    assert '"100.64.0.10"' in body
