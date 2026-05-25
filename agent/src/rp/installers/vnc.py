"""TigerVNC server installer (Linux GUI fallback)."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path
from typing import Optional

import structlog

from rp.installers.base import (
    InstallResult,
    InstallerError,
    ensure_rp_config_dir,
    run_subprocess,
    write_secure_toml,
)
from rp.platform_detect import get_distro, get_os

logger = structlog.get_logger(__name__)


VNC_CONFIG_FILENAME = "vnc.toml"


class VNCInstaller:
    """TigerVNC server installer for Linux GUI fallback.

    Linux-only; requires an X11 server (X.org or Xwayland) for display :1.
    """

    @staticmethod
    def _ensure_linux() -> None:
        if get_os() != "linux":
            raise InstallerError("VNC install is only supported on Linux hosts.")

    @staticmethod
    def _has_x11() -> bool:
        """Best-effort X11 detection."""
        return bool(
            shutil.which("Xorg")
            or shutil.which("Xwayland")
            or os.environ.get("DISPLAY")
        )

    async def detect_installed(self) -> bool:
        """Return True if TigerVNC server is installed."""
        return any(
            shutil.which(b) is not None for b in ("vncserver", "Xvnc", "x0vncserver")
        )

    async def install(self, force: bool = False) -> InstallResult:
        """Install TigerVNC server via the system package manager."""
        self._ensure_linux()

        if not self._has_x11():
            raise InstallerError(
                "No X11 server detected (Xorg/Xwayland/DISPLAY). "
                "VNC fallback requires a GUI Linux host."
            )

        if not force and await self.detect_installed():
            return InstallResult(
                tool="vnc",
                installed=True,
                method="preexisting",
                skipped=True,
                message="TigerVNC already installed (use --force to reinstall).",
            )

        distro = (get_distro() or "").lower()
        if any(d in distro for d in ("debian", "ubuntu", "raspbian", "mint")):
            await run_subprocess(
                ["apt-get", "update"],
                check=False,
                env={"DEBIAN_FRONTEND": "noninteractive"},
            )
            await run_subprocess(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "tigervnc-standalone-server",
                    "tigervnc-common",
                ],
                check=True,
                env={"DEBIAN_FRONTEND": "noninteractive"},
            )
            method = "apt"
        elif any(d in distro for d in ("fedora", "rhel", "centos", "rocky", "alma")):
            installer = "dnf" if shutil.which("dnf") else "yum"
            await run_subprocess(
                [installer, "install", "-y", "tigervnc-server"], check=True
            )
            method = installer
        elif "arch" in distro or "manjaro" in distro:
            await run_subprocess(
                ["pacman", "-S", "--noconfirm", "tigervnc"], check=True
            )
            method = "pacman"
        else:
            raise InstallerError(
                f"Unsupported Linux distro for VNC install: {distro or 'unknown'}"
            )

        return InstallResult(
            tool="vnc",
            installed=await self.detect_installed(),
            method=method,
            message="Installed TigerVNC server",
        )

    async def configure(
        self, *, tailscale_ip: Optional[str] = None, port: int = 5901
    ) -> dict[str, object]:
        """Configure VNC password + bind addr; write rp-managed config."""
        self._ensure_linux()

        password = secrets.token_urlsafe(24)
        bind_addr = tailscale_ip or "0.0.0.0"

        rp_config_path = ensure_rp_config_dir() / VNC_CONFIG_FILENAME
        body = (
            "# rp-managed VNC config\n"
            f'password = "{password}"\n'
            f"port = {port}\n"
            f'bind_addr = "{bind_addr}"\n'
        )
        write_secure_toml(rp_config_path, body)

        logger.info("vnc_configured", port=port, bind=bind_addr)
        return {
            "port": port,
            "password": password,
            "bind_addr": bind_addr,
            "config_path": str(rp_config_path),
        }

    async def uninstall(self) -> None:
        """Best-effort uninstall + clean rp config."""
        distro = (get_distro() or "").lower()
        if any(d in distro for d in ("debian", "ubuntu", "raspbian", "mint")):
            await run_subprocess(
                [
                    "apt-get",
                    "remove",
                    "-y",
                    "tigervnc-standalone-server",
                    "tigervnc-common",
                ],
                check=False,
                env={"DEBIAN_FRONTEND": "noninteractive"},
            )
        elif any(d in distro for d in ("fedora", "rhel", "centos", "rocky", "alma")):
            installer = "dnf" if shutil.which("dnf") else "yum"
            await run_subprocess(
                [installer, "remove", "-y", "tigervnc-server"], check=False
            )
        elif "arch" in distro or "manjaro" in distro:
            await run_subprocess(
                ["pacman", "-Rs", "--noconfirm", "tigervnc"], check=False
            )
        rp_path = ensure_rp_config_dir() / VNC_CONFIG_FILENAME
        rp_path.unlink(missing_ok=True)


# Re-export Path so tests can patch easily.
__all__ = ["VNCInstaller", "Path"]
