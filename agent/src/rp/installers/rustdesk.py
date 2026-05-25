"""RustDesk client installer + Direct IP configurator (F6-1).

Cross-OS install:

- Debian/Ubuntu: ``.deb`` from GitHub Releases, ``dpkg -i`` + ``apt -f install``.
- Fedora/RHEL: ``.rpm`` from GitHub Releases, ``dnf install``.
- Arch: ``paru -S rustdesk-bin`` (AUR; falls back to ``yay`` if present).
- macOS: ``brew install --cask rustdesk`` (brew assumed installed).
- Windows: ``winget install RustDesk.RustDesk`` (winget assumed installed).

Configuration writes:

- ``/etc/rp/rustdesk.toml``   — rp-managed (password + bind iface + version).
- ``~/.config/rustdesk/RustDesk2.toml`` — patches Direct IP + bind addr.
"""

from __future__ import annotations

import platform
import re
import secrets
import shutil
import sys
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
from rp.platform_detect import get_distro, get_os

logger = structlog.get_logger(__name__)


RUSTDESK_REPO = "rustdesk/rustdesk"
RUSTDESK_RELEASE_API = f"https://api.github.com/repos/{RUSTDESK_REPO}/releases/latest"
RUSTDESK_CONFIG_FILENAME = "rustdesk.toml"


class RustDeskInstaller:
    """Cross-OS RustDesk client installer + configurator."""

    def __init__(self, *, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http_client = http_client

    async def detect_installed(self) -> bool:
        """Return True if RustDesk binary/app is present locally."""
        if shutil.which("rustdesk"):
            return True

        os_type = get_os()
        if os_type == "macos":
            return Path("/Applications/RustDesk.app").exists()
        if os_type == "windows":
            return Path("C:/Program Files/RustDesk/rustdesk.exe").exists()
        return False

    async def detect_version(self) -> Optional[str]:
        """Return ``rustdesk --version`` output (best-effort)."""
        binary = shutil.which("rustdesk")
        if not binary and get_os() == "macos":
            candidate = Path("/Applications/RustDesk.app/Contents/MacOS/RustDesk")
            binary = str(candidate) if candidate.exists() else None
        if not binary:
            return None

        try:
            _, stdout, _ = await run_subprocess(
                [binary, "--version"], check=False, timeout=5
            )
        except InstallerError:
            return None
        match = re.search(r"\d+\.\d+\.\d+", stdout)
        return match.group(0) if match else stdout.strip() or None

    async def install(self, force: bool = False) -> InstallResult:
        """Install RustDesk via the OS-native method.

        Idempotent: returns a skipped result if already installed and not
        ``force``.
        """
        if not force and await self.detect_installed():
            version = await self.detect_version()
            logger.info("rustdesk_already_installed", version=version)
            return InstallResult(
                tool="rustdesk",
                installed=True,
                version=version,
                method="preexisting",
                skipped=True,
                message="RustDesk already installed (use --force to reinstall).",
            )

        os_type = get_os()
        if os_type == "linux":
            return await self._install_linux(force)
        if os_type == "macos":
            return await self._install_macos(force)
        if os_type == "windows":
            return await self._install_windows(force)
        raise InstallerError(f"Unsupported OS for RustDesk install: {os_type}")

    # --- platform-specific install ---------------------------------------

    async def _install_linux(self, force: bool) -> InstallResult:
        distro = (get_distro() or "").lower()
        logger.info("rustdesk_install_linux", distro=distro)

        if any(d in distro for d in ("debian", "ubuntu", "raspbian", "mint")):
            return await self._install_linux_deb(force)
        if any(d in distro for d in ("fedora", "rhel", "centos", "rocky", "alma")):
            return await self._install_linux_rpm(force)
        if "arch" in distro or "manjaro" in distro:
            return await self._install_linux_arch(force)

        raise InstallerError(
            f"Unsupported Linux distro for RustDesk install: {distro or 'unknown'}"
        )

    async def _install_linux_deb(self, force: bool) -> InstallResult:
        asset = await self._fetch_release_asset(suffix=".deb", arch_hint="x86_64")
        deb_path = await self._download_asset(asset["browser_download_url"])
        try:
            await run_subprocess(["dpkg", "-i", str(deb_path)], check=False)
            # Fix any missing deps.
            await run_subprocess(
                ["apt-get", "install", "-f", "-y"],
                check=False,
                env={"DEBIAN_FRONTEND": "noninteractive"},
            )
        finally:
            deb_path.unlink(missing_ok=True)

        version = await self.detect_version()
        return InstallResult(
            tool="rustdesk",
            installed=await self.detect_installed(),
            version=version,
            method="dpkg",
            message=f"Installed RustDesk {version} via .deb",
        )

    async def _install_linux_rpm(self, force: bool) -> InstallResult:
        asset = await self._fetch_release_asset(suffix=".rpm", arch_hint="x86_64")
        rpm_path = await self._download_asset(asset["browser_download_url"])
        try:
            installer = "dnf" if shutil.which("dnf") else "yum"
            await run_subprocess(
                [installer, "install", "-y", str(rpm_path)], check=True
            )
        finally:
            rpm_path.unlink(missing_ok=True)

        version = await self.detect_version()
        return InstallResult(
            tool="rustdesk",
            installed=await self.detect_installed(),
            version=version,
            method="rpm",
            message=f"Installed RustDesk {version} via .rpm",
        )

    async def _install_linux_arch(self, force: bool) -> InstallResult:
        helper = next(
            (b for b in ("paru", "yay") if shutil.which(b)),
            None,
        )
        if not helper:
            raise InstallerError("Arch install requires an AUR helper (paru or yay).")
        await run_subprocess([helper, "-S", "--noconfirm", "rustdesk-bin"], check=True)
        version = await self.detect_version()
        return InstallResult(
            tool="rustdesk",
            installed=await self.detect_installed(),
            version=version,
            method=f"aur:{helper}",
            message=f"Installed RustDesk {version} via {helper}",
        )

    async def _install_macos(self, force: bool) -> InstallResult:
        if not shutil.which("brew"):
            raise InstallerError(
                "macOS install requires Homebrew. Install brew first: https://brew.sh"
            )
        args = ["brew", "install", "--cask", "rustdesk"]
        if force:
            args.insert(2, "--force")
        rc, _, stderr = await run_subprocess(args, check=False, timeout=600)
        if rc != 0:
            raise InstallerError(f"brew install rustdesk failed: {stderr.strip()}")

        version = await self.detect_version()
        return InstallResult(
            tool="rustdesk",
            installed=await self.detect_installed(),
            version=version,
            method="brew-cask",
            message=f"Installed RustDesk {version} via brew",
        )

    async def _install_windows(self, force: bool) -> InstallResult:
        if not shutil.which("winget"):
            raise InstallerError(
                "Windows install requires winget. Install App Installer "
                "from the Microsoft Store."
            )
        args = [
            "winget",
            "install",
            "--id",
            "RustDesk.RustDesk",
            "--silent",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]
        if force:
            args.append("--force")
        rc, _, stderr = await run_subprocess(args, check=False, timeout=900)
        if rc != 0:
            raise InstallerError(f"winget install RustDesk failed: {stderr.strip()}")

        version = await self.detect_version()
        return InstallResult(
            tool="rustdesk",
            installed=await self.detect_installed(),
            version=version,
            method="winget",
            message=f"Installed RustDesk {version} via winget",
        )

    # --- configuration ----------------------------------------------------

    async def configure_direct_ip(
        self,
        password: Optional[str] = None,
        tailscale_ip: Optional[str] = None,
    ) -> dict[str, object]:
        """Configure Direct IP mode + bind to Tailscale interface only.

        Args:
            password: Custom password; defaults to ``secrets.token_urlsafe(32)``.
            tailscale_ip: Optional Tailscale IPv4 to bind. If None, ``0.0.0.0``
                is used and access is gated by tailnet ACLs.

        Returns:
            Mapping with ``password``, ``id_server``, ``relay_server``,
            ``direct_ip`` (bind address).
        """
        ensure_rp_config_dir()

        if password is None:
            password = secrets.token_urlsafe(32)
        if len(password) < 16:
            raise InstallerError(
                "Password must be at least 16 chars for Direct IP mode."
            )

        bind_addr = tailscale_ip or "0.0.0.0"
        version = await self.detect_version() or "unknown"

        # 1) rp-managed config (machine-readable, single source of truth).
        rp_toml = (
            "# rp-managed RustDesk config (do not edit by hand)\n"
            f'password = "{password}"\n'
            f'bind_addr = "{bind_addr}"\n'
            'id_server = "direct"\n'
            'relay_server = "none"\n'
            f'rustdesk_version = "{version}"\n'
            "direct_ip_access = true\n"
        )
        rp_config_path = ensure_rp_config_dir() / RUSTDESK_CONFIG_FILENAME
        write_secure_toml(rp_config_path, rp_toml)

        # 2) Patch RustDesk's own config file (best-effort; user dirs vary).
        await self._patch_rustdesk_native_config(password=password, bind_addr=bind_addr)

        logger.info(
            "rustdesk_configured_direct_ip",
            bind=bind_addr,
            password_len=len(password),
        )

        return {
            "password": password,
            "id_server": "direct",
            "relay_server": "none",
            "direct_ip": bind_addr,
            "config_path": str(rp_config_path),
        }

    async def _patch_rustdesk_native_config(
        self, password: str, bind_addr: str
    ) -> None:
        """Patch RustDesk's own TOML (RustDesk2.toml) for Direct IP."""
        candidates: list[Path] = []
        home = Path.home()
        os_type = get_os()

        if os_type == "linux":
            candidates.append(home / ".config" / "rustdesk" / "RustDesk2.toml")
        elif os_type == "macos":
            candidates.append(
                home
                / "Library"
                / "Preferences"
                / "com.carriez.RustDesk"
                / "RustDesk2.toml"
            )
            candidates.append(home / ".config" / "rustdesk" / "RustDesk2.toml")
        elif os_type == "windows":
            appdata = Path.home() / "AppData" / "Roaming" / "RustDesk" / "config"
            candidates.append(appdata / "RustDesk2.toml")

        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                existing = path.read_text() if path.exists() else ""
            except OSError as exc:
                logger.debug(
                    "rustdesk_native_config_unreadable",
                    path=str(path),
                    error=str(exc),
                )
                continue

            patched = self._merge_rustdesk_toml(
                existing, password=password, bind_addr=bind_addr
            )
            try:
                path.write_text(patched)
                logger.info("rustdesk_native_config_patched", path=str(path))
                return
            except OSError as exc:
                logger.warning(
                    "rustdesk_native_config_write_failed",
                    path=str(path),
                    error=str(exc),
                )

        logger.warning(
            "rustdesk_native_config_not_patched",
            reason="no writable candidate path",
        )

    @staticmethod
    def _merge_rustdesk_toml(existing: str, password: str, bind_addr: str) -> str:
        """Merge Direct IP options into an existing RustDesk2.toml body."""
        # Naïve key replace; RustDesk's TOML is flat enough for this.
        wanted = {
            "password": f'"{password}"',
            "direct-access": "true",
            "direct-server": "true",
            "direct-access-port": "21118",
            "direct-access-bind": f'"{bind_addr}"',
            "rendezvous-server": '""',
            "relay-server": '""',
            "custom-rendezvous-server": '""',
        }
        lines = existing.splitlines() if existing else []
        seen: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in wanted:
                    new_lines.append(f"{key} = {wanted[key]}")
                    seen.add(key)
                    continue
            new_lines.append(line)
        for key, value in wanted.items():
            if key not in seen:
                new_lines.append(f"{key} = {value}")
        return "\n".join(new_lines) + "\n"

    async def uninstall(self) -> None:
        """Best-effort uninstall + clean rp config files."""
        os_type = get_os()
        try:
            if os_type == "linux":
                distro = (get_distro() or "").lower()
                if "debian" in distro or "ubuntu" in distro:
                    await run_subprocess(["dpkg", "--remove", "rustdesk"], check=False)
                elif "fedora" in distro or "rhel" in distro:
                    installer = "dnf" if shutil.which("dnf") else "yum"
                    await run_subprocess(
                        [installer, "remove", "-y", "rustdesk"], check=False
                    )
            elif os_type == "macos" and shutil.which("brew"):
                await run_subprocess(
                    ["brew", "uninstall", "--cask", "rustdesk"], check=False
                )
            elif os_type == "windows" and shutil.which("winget"):
                await run_subprocess(
                    ["winget", "uninstall", "--id", "RustDesk.RustDesk"],
                    check=False,
                )
        finally:
            rp_path = ensure_rp_config_dir() / RUSTDESK_CONFIG_FILENAME
            rp_path.unlink(missing_ok=True)

    # --- helpers ----------------------------------------------------------

    async def _fetch_release_asset(
        self, *, suffix: str, arch_hint: str
    ) -> dict[str, object]:
        """Fetch latest release metadata and pick asset by suffix + arch."""
        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        try:
            assert client is not None
            resp = await client.get(RUSTDESK_RELEASE_API)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns_client and client is not None:
                await client.aclose()

        machine = platform.machine().lower()
        if machine in ("amd64", "x86_64"):
            arches = ("x86_64", "amd64")
        elif machine in ("aarch64", "arm64"):
            arches = ("aarch64", "arm64")
        else:
            arches = (machine,)

        assets = data.get("assets", [])
        for asset in assets:
            name = str(asset.get("name", "")).lower()
            if name.endswith(suffix) and any(a in name for a in arches):
                return asset

        raise InstallerError(
            f"No release asset matching suffix={suffix} arch={arch_hint} "
            f"found in {RUSTDESK_REPO} latest release."
        )

    async def _download_asset(self, url: str) -> Path:
        """Download an asset to a temp file. Caller deletes."""
        import tempfile

        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=300.0, follow_redirects=True)
        try:
            assert client is not None
            suffix = Path(url).suffix
            tmp = Path(tempfile.mkstemp(suffix=suffix, prefix="rustdesk-")[1])
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                        fh.write(chunk)
            return tmp
        finally:
            if owns_client and client is not None:
                await client.aclose()


def _is_windows() -> bool:
    return sys.platform.startswith("win")
