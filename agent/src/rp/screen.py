"""Screen sharing and remote desktop capabilities (F6).

RustDesk Direct IP, Sunshine, and VNC launcher for remote screen control.
"""

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ResolvedHost:
    """Resolved host with Tailscale connectivity and capabilities."""

    hostname: str
    tailscale_ip: str
    magicdns_name: str
    capabilities: dict[str, Any]
    group: str


class HostResolver:
    """Resolve target hostname to Tailscale IP and capabilities."""

    def __init__(self, client: Any):
        """
        Initialize resolver.

        Args:
            client: RPClient instance for API calls
        """
        self.client = client

    async def resolve(self, target: str) -> ResolvedHost:
        """
        Resolve target name to Tailscale IP and capabilities.

        Strategy:
        1. Query rp-server /v1/hosts to find by hostname/fqdn.
        2. Read host.capabilities (rustdesk_password, sunshine_enabled, etc).
        3. Return ResolvedHost with connectivity info.

        Args:
            target: Hostname, FQDN, or partial match

        Returns:
            ResolvedHost with IP and capabilities

        Raises:
            ValueError: If target not found or ambiguous
            httpx.HTTPError: If API request fails
        """
        logger.info("resolving_host", target=target)

        # Query server for hosts
        response = await self.client.get("/v1/hosts")
        response.raise_for_status()

        hosts = response.json()

        # Find matching host (case-insensitive substring match)
        matches = [
            h
            for h in hosts
            if target.lower() in h["hostname"].lower()
            or target.lower() in h.get("fqdn", "").lower()
        ]

        if not matches:
            raise ValueError(f"No host found matching '{target}'")

        if len(matches) > 1:
            hostnames = [h["hostname"] for h in matches]
            raise ValueError(
                f"Ambiguous target '{target}' matches: {', '.join(hostnames)}"
            )

        host = matches[0]

        # Extract Tailscale info from capabilities or network data
        capabilities = host.get("capabilities", {})
        tailscale_ip = capabilities.get("tailscale_ip", "")
        magicdns_name = host["hostname"]  # Default to hostname

        # Try to get MagicDNS from Tailscale node info if available
        if capabilities.get("tailscale_node_id"):
            magicdns_name = f"{host['hostname']}.monxas.ts.net"

        if not tailscale_ip:
            raise ValueError(f"Host '{target}' has no Tailscale IP")

        logger.info(
            "host_resolved",
            hostname=host["hostname"],
            ip=tailscale_ip,
            magicdns=magicdns_name,
        )

        return ResolvedHost(
            hostname=host["hostname"],
            tailscale_ip=tailscale_ip,
            magicdns_name=magicdns_name,
            capabilities=capabilities,
            group=host.get("group", "unknown"),
        )


class RustDeskLauncher:
    """Launch local RustDesk client connected to remote host."""

    async def launch(self, host: ResolvedHost, password: Optional[str] = None) -> int:
        """
        Spawn local RustDesk client connected via Direct IP to host.

        Args:
            host: Resolved target host
            password: Optional password override (uses host capability if None)

        Returns:
            Exit code of RustDesk process

        Raises:
            FileNotFoundError: If RustDesk not installed
            ValueError: If host doesn't have RustDesk capability
        """
        # Check if RustDesk installed locally
        rustdesk_bin = self._find_rustdesk_binary()
        if not rustdesk_bin:
            raise FileNotFoundError("RustDesk not installed. Run: rp install rustdesk")

        # Get password from capabilities if not provided
        if password is None:
            password = host.capabilities.get("rustdesk_password")

        if not password:
            raise ValueError(
                f"Host '{host.hostname}' has no rustdesk_password capability"
            )

        logger.info(
            "launching_rustdesk",
            host=host.hostname,
            ip=host.tailscale_ip,
        )

        # RustDesk CLI: rustdesk --connect <ip> --password <pass>
        # Direct IP mode (no relay/rendezvous server)
        args = [rustdesk_bin, "--connect", host.tailscale_ip, "--password", password]

        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        logger.info("rustdesk_launched", pid=proc.pid)

        # Wait for process (blocking)
        return proc.wait()

    def _find_rustdesk_binary(self) -> Optional[str]:
        """Find RustDesk binary path for current platform."""
        # Try standard path first
        if binary := shutil.which("rustdesk"):
            return binary

        # Platform-specific paths
        system = platform.system()

        if system == "Darwin":
            app_path = "/Applications/RustDesk.app/Contents/MacOS/RustDesk"
            if Path(app_path).exists():
                return app_path

        elif system == "Windows":
            program_files = Path("C:/Program Files/RustDesk")
            if (program_files / "rustdesk.exe").exists():
                return str(program_files / "rustdesk.exe")

        return None


class SunshineLauncher:
    """Launch local Moonlight client connecting to Sunshine host."""

    async def launch(self, host: ResolvedHost) -> int:
        """
        Spawn local Moonlight client connecting to Sunshine host.

        Args:
            host: Resolved target host (must have sunshine_enabled capability)

        Returns:
            Exit code of Moonlight process

        Raises:
            FileNotFoundError: If Moonlight not installed
            ValueError: If host doesn't have Sunshine capability
        """
        # Check if Sunshine enabled on host
        if not host.capabilities.get("sunshine_enabled"):
            raise ValueError(f"Host '{host.hostname}' does not have Sunshine enabled")

        # Check if Moonlight installed locally
        moonlight_bin = self._find_moonlight_binary()
        if not moonlight_bin:
            raise FileNotFoundError(
                "Moonlight not installed. Install from: https://moonlight-stream.org"
            )

        logger.info(
            "launching_moonlight",
            host=host.hostname,
            ip=host.tailscale_ip,
        )

        # Moonlight CLI: moonlight stream <ip>
        args = [moonlight_bin, "stream", host.tailscale_ip]

        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        logger.info("moonlight_launched", pid=proc.pid)

        return proc.wait()

    def _find_moonlight_binary(self) -> Optional[str]:
        """Find Moonlight binary path for current platform."""
        # Try moonlight CLI first
        for name in ["moonlight", "moonlight-qt"]:
            if binary := shutil.which(name):
                return binary

        # Platform-specific paths
        system = platform.system()

        if system == "Darwin":
            app_path = "/Applications/Moonlight.app/Contents/MacOS/Moonlight"
            if Path(app_path).exists():
                return app_path

        elif system == "Windows":
            program_files = Path("C:/Program Files/Moonlight")
            if (program_files / "Moonlight.exe").exists():
                return str(program_files / "Moonlight.exe")

        return None


class VNCLauncher:
    """Launch local VNC client (TigerVNC/Remmina fallback for Linux)."""

    async def launch(self, host: ResolvedHost, port: int = 5900) -> int:
        """
        Spawn local VNC client.

        Args:
            host: Resolved target host
            port: VNC port (default 5900)

        Returns:
            Exit code of VNC client process

        Raises:
            FileNotFoundError: If no VNC client found
            ValueError: If host doesn't have VNC capability
        """
        if not host.capabilities.get("vnc_installed"):
            raise ValueError(f"Host '{host.hostname}' does not have VNC enabled")

        vnc_bin = self._find_vnc_viewer()
        if not vnc_bin:
            raise FileNotFoundError(
                "No VNC client installed. Install: vncviewer, tigervnc, or remmina"
            )

        logger.info(
            "launching_vnc",
            host=host.hostname,
            ip=host.tailscale_ip,
            port=port,
        )

        # VNC connection string: ip:port or ip::port depending on client
        vnc_addr = (
            f"{host.tailscale_ip}::{port}"
            if "tiger" in vnc_bin
            else f"{host.tailscale_ip}:{port}"
        )

        args = [vnc_bin, vnc_addr]

        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        logger.info("vnc_launched", pid=proc.pid)

        return proc.wait()

    def _find_vnc_viewer(self) -> Optional[str]:
        """Find VNC viewer binary."""
        for name in ["vncviewer", "tigervnc", "remmina"]:
            if binary := shutil.which(name):
                return binary

        return None
