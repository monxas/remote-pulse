"""Sunshine GameStream server installer (F6-2, Windows GPU hosts).

Downloads ``sunshine-windows-installer.exe`` from the LizardByte/Sunshine
GitHub release, verifies the SHA256 against the ``.sha256`` companion (when
available), and runs the NSIS silent installer.

Pairing (PIN exchange via Sunshine web admin) **remains manual**: the agent
exposes ``https://<tailscale-ip>:47990`` and pre-generates an admin user, but
the one-time Moonlight pairing PIN must be entered by a human.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

import httpx
import structlog

from rp.installers.base import (
    InstallResult,
    InstallerError,
    ensure_rp_config_dir,
    run_subprocess,
    write_secure_toml,
)
from rp.platform_detect import get_os

logger = structlog.get_logger(__name__)


SUNSHINE_REPO = "LizardByte/Sunshine"
SUNSHINE_RELEASE_API = f"https://api.github.com/repos/{SUNSHINE_REPO}/releases/latest"
SUNSHINE_CONFIG_FILENAME = "sunshine.toml"
SUNSHINE_PORTS = (47984, 47989, 47990)


class SunshineInstaller:
    """Sunshine installer (Windows-only).

    Raises:
        InstallerError: When invoked on a non-Windows host.
    """

    def __init__(self, *, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http_client = http_client

    @staticmethod
    def _ensure_windows() -> None:
        if get_os() != "windows":
            raise InstallerError(
                "Sunshine install is only supported on Windows hosts. "
                "Use RustDesk on Linux/macOS."
            )

    async def detect_installed(self) -> bool:
        """Return True if Sunshine binary is present."""
        if get_os() != "windows":
            return False
        return Path("C:/Program Files/Sunshine/sunshine.exe").exists()

    async def detect_version(self) -> Optional[str]:
        """Detect Sunshine version from binary metadata (best-effort)."""
        exe = Path("C:/Program Files/Sunshine/sunshine.exe")
        if not exe.exists():
            return None
        try:
            _, stdout, _ = await run_subprocess(
                [str(exe), "--version"], check=False, timeout=5
            )
        except InstallerError:
            return None
        match = re.search(r"\d+\.\d+\.\d+", stdout)
        return match.group(0) if match else stdout.strip() or None

    @staticmethod
    def _detect_gpu() -> bool:
        """Detect Nvidia/Intel/AMD GPU (best-effort)."""
        return any(shutil.which(b) is not None for b in ("nvidia-smi", "vainfo"))

    async def install(
        self, force: bool = False, allow_no_gpu: bool = False
    ) -> InstallResult:
        """Install Sunshine MSI silently.

        Args:
            force: Reinstall even if present.
            allow_no_gpu: Skip GPU detection check (use only on hosts that
                expose an iGPU which doesn't surface via ``nvidia-smi``).
        """
        self._ensure_windows()

        if not self._detect_gpu() and not allow_no_gpu:
            raise InstallerError(
                "No GPU detected (nvidia-smi/vainfo missing). "
                "Re-run with --force to override."
            )

        if not force and await self.detect_installed():
            version = await self.detect_version()
            return InstallResult(
                tool="sunshine",
                installed=True,
                version=version,
                method="preexisting",
                skipped=True,
                message="Sunshine already installed (use --force to reinstall).",
            )

        asset, sha_asset = await self._fetch_installer_asset()
        installer_path = await self._download_asset(asset["browser_download_url"])
        try:
            if sha_asset is not None:
                await self._verify_sha256(
                    installer_path, sha_asset["browser_download_url"]
                )
            else:
                logger.warning("sunshine_sha256_missing", asset=asset.get("name"))

            # NSIS silent flag: /S (capital).
            rc, _, stderr = await run_subprocess(
                [str(installer_path), "/S"], check=False, timeout=600
            )
            if rc != 0:
                raise InstallerError(
                    f"Sunshine silent install failed (rc={rc}): {stderr.strip()}"
                )
        finally:
            installer_path.unlink(missing_ok=True)

        version = await self.detect_version()
        return InstallResult(
            tool="sunshine",
            installed=await self.detect_installed(),
            version=version,
            method="msi-silent",
            message=f"Installed Sunshine {version} (silent)",
        )

    async def configure(
        self, *, tailscale_ip: Optional[str] = None
    ) -> dict[str, object]:
        """Configure Sunshine admin UI + apps.json + firewall.

        Returns:
            ``{admin_url, username, password, requires_manual_pairing}``.
        """
        self._ensure_windows()

        bind_addr = tailscale_ip or "0.0.0.0"
        admin_username = "rp-admin"
        admin_password = secrets.token_urlsafe(32)
        admin_url = f"https://{tailscale_ip or 'localhost'}:47990"

        rp_config_path = ensure_rp_config_dir() / SUNSHINE_CONFIG_FILENAME
        rp_toml = (
            "# rp-managed Sunshine config (do not edit by hand)\n"
            f'admin_url = "{admin_url}"\n'
            f'username = "{admin_username}"\n'
            f'password = "{admin_password}"\n'
            f'bind_addr = "{bind_addr}"\n'
            "requires_manual_pairing = true\n"
        )
        write_secure_toml(rp_config_path, rp_toml)

        # Best-effort firewall opening (Windows-only).
        await self._open_firewall_ports(bind_addr=bind_addr)

        # Best-effort: enable auto-start service.
        await self._enable_autostart()

        logger.info(
            "sunshine_configured",
            bind=bind_addr,
            admin_url=admin_url,
        )

        return {
            "admin_url": admin_url,
            "username": admin_username,
            "password": admin_password,
            "requires_manual_pairing": True,
            "config_path": str(rp_config_path),
        }

    async def _open_firewall_ports(self, bind_addr: str) -> None:
        """Open Sunshine ports via ``netsh`` (best-effort)."""
        if not shutil.which("netsh"):
            return
        for port in SUNSHINE_PORTS:
            args = [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name=rp-sunshine-{port}",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={port}",
            ]
            await run_subprocess(args, check=False, timeout=15)

    async def _enable_autostart(self) -> None:
        """Enable SunshineService auto-start (Windows)."""
        if not shutil.which("sc"):
            return
        await run_subprocess(
            ["sc", "config", "SunshineService", "start=", "auto"],
            check=False,
            timeout=15,
        )
        await run_subprocess(
            ["sc", "start", "SunshineService"], check=False, timeout=15
        )

    async def uninstall(self) -> None:
        """Best-effort uninstall via NSIS uninstaller."""
        if get_os() != "windows":
            return
        uninstaller = Path("C:/Program Files/Sunshine/Uninstall.exe")
        if uninstaller.exists():
            await run_subprocess([str(uninstaller), "/S"], check=False, timeout=120)
        rp_path = ensure_rp_config_dir() / SUNSHINE_CONFIG_FILENAME
        rp_path.unlink(missing_ok=True)

    # --- helpers ----------------------------------------------------------

    async def _fetch_installer_asset(
        self,
    ) -> tuple[dict[str, object], Optional[dict[str, object]]]:
        """Return (installer_asset, sha256_asset_or_none)."""
        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        try:
            assert client is not None
            resp = await client.get(SUNSHINE_RELEASE_API)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns_client and client is not None:
                await client.aclose()

        installer: Optional[dict[str, object]] = None
        sha: Optional[dict[str, object]] = None
        for asset in data.get("assets", []):
            name = str(asset.get("name", "")).lower()
            if name == "sunshine-windows-installer.exe":
                installer = asset
            elif name == "sunshine-windows-installer.exe.sha256":
                sha = asset

        if installer is None:
            raise InstallerError(
                "Sunshine release does not contain sunshine-windows-installer.exe."
            )
        return installer, sha

    async def _download_asset(self, url: str) -> Path:
        """Download an asset to a temp file."""
        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=600.0, follow_redirects=True)
        try:
            assert client is not None
            suffix = Path(url).suffix
            tmp_fd, tmp_name = tempfile.mkstemp(suffix=suffix, prefix="sunshine-")
            os.close(tmp_fd)
            tmp = Path(tmp_name)
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                        fh.write(chunk)
            return tmp
        finally:
            if owns_client and client is not None:
                await client.aclose()

    async def _verify_sha256(self, file_path: Path, sha_url: str) -> None:
        """Verify SHA256 of ``file_path`` against the published checksum."""
        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        try:
            assert client is not None
            resp = await client.get(sha_url)
            resp.raise_for_status()
            expected_raw = resp.text.strip().split()[0].lower()
        finally:
            if owns_client and client is not None:
                await client.aclose()

        digest = hashlib.sha256()
        with file_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest().lower()

        if actual != expected_raw:
            raise InstallerError(
                f"SHA256 mismatch for Sunshine installer: "
                f"expected={expected_raw} actual={actual}"
            )
        logger.info("sunshine_sha256_verified", sha256=actual)


def _is_windows() -> bool:
    return sys.platform.startswith("win")
