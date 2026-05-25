"""Smart SSH wrapper preferring Tailscale SSH (F6).

Tries Tailscale SSH first, falls back to classic SSH with managed keys.
"""

import shutil
import subprocess
from typing import Any, Optional

import structlog

from rp.screen import HostResolver, ResolvedHost
from rp.ssh_keys import HOST_KEY_PATH

logger = structlog.get_logger(__name__)


class SSHWrapper:
    """Smart SSH wrapper preferring Tailscale SSH."""

    def __init__(self, client: Any):
        """
        Initialize SSH wrapper.

        Args:
            client: RPClient instance for host resolution
        """
        self.client = client
        self.resolver = HostResolver(client)

    async def connect(
        self,
        target: str,
        command: Optional[list[str]] = None,
        user: Optional[str] = None,
        port: Optional[int] = None,
        force_classic: bool = False,
    ) -> int:
        """
        Connect to target via SSH.

        Tries in order:
        1. Tailscale SSH (if target has capability and not force_classic)
        2. SSH classic with managed key fallback

        Args:
            target: Hostname (resolved via HostResolver), MagicDNS name, or IP
            command: Optional remote command (defaults to interactive shell)
            user: Remote user (defaults to current user)
            port: SSH port (defaults to 22)
            force_classic: Skip Tailscale SSH, use classic only

        Returns:
            Exit code of the SSH process
        """
        # Resolve target
        try:
            resolved = await self.resolver.resolve(target)
        except Exception as e:
            logger.error("host_resolution_failed", target=target, error=str(e))
            print(f"Error: Could not resolve host '{target}': {e}")
            return 1

        # Try Tailscale SSH first (unless forced classic)
        if not force_classic and await self._should_use_tailscale_ssh(resolved):
            logger.info("attempting_tailscale_ssh", host=resolved.hostname)
            exit_code = await self._tailscale_ssh(resolved, command, user)

            if exit_code == 0:
                return 0

            logger.warning("tailscale_ssh_failed_fallback_classic")
            print("Tailscale SSH failed, falling back to classic SSH...")

        # Fallback to classic SSH with managed key
        return await self._classic_ssh(resolved, command, user, port)

    async def _should_use_tailscale_ssh(self, resolved: ResolvedHost) -> bool:
        """Check if Tailscale SSH should be used."""
        # Check if Tailscale SSH available locally
        if not self.detect_tailscale_ssh():
            logger.debug("tailscale_ssh_not_available_locally")
            return False

        # Check if target has Tailscale SSH enabled
        return await self.is_target_ts_ssh_capable(resolved)

    def detect_tailscale_ssh(self) -> bool:
        """Check if `tailscale ssh` command exists locally (Tailscale 1.30+)."""
        tailscale_bin = shutil.which("tailscale")
        if not tailscale_bin:
            return False

        try:
            result = subprocess.run(
                [tailscale_bin, "ssh", "--help"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    async def is_target_ts_ssh_capable(self, resolved: ResolvedHost) -> bool:
        """Query host capabilities for tailscale_ssh_enabled flag."""
        return resolved.capabilities.get("tailscale_ssh_enabled", False)

    async def _tailscale_ssh(
        self,
        resolved: ResolvedHost,
        command: Optional[list[str]] = None,
        user: Optional[str] = None,
    ) -> int:
        """
        Execute SSH via Tailscale SSH.

        Args:
            resolved: Resolved host
            command: Optional remote command
            user: Optional user (defaults to current)

        Returns:
            Exit code
        """
        tailscale_bin = shutil.which("tailscale")
        if not tailscale_bin:
            return 1

        # Build command: tailscale ssh [user@]host [command]
        target = f"{user}@{resolved.magicdns_name}" if user else resolved.magicdns_name

        args = [tailscale_bin, "ssh", target]

        if command:
            args.extend(["--"] + command)

        logger.info("exec_tailscale_ssh", args=args)

        # Run SSH (passthrough stdin/stdout/stderr for interactive)
        proc = subprocess.run(args, check=False)

        return proc.returncode

    async def _classic_ssh(
        self,
        resolved: ResolvedHost,
        command: Optional[list[str]] = None,
        user: Optional[str] = None,
        port: Optional[int] = None,
    ) -> int:
        """
        Execute SSH via classic OpenSSH with managed key.

        Args:
            resolved: Resolved host
            command: Optional remote command
            user: Optional user
            port: Optional port

        Returns:
            Exit code
        """
        ssh_bin = shutil.which("ssh")
        if not ssh_bin:
            logger.error("ssh_not_found")
            print("Error: ssh command not found")
            return 1

        # Build SSH command
        target = f"{user}@{resolved.tailscale_ip}" if user else resolved.tailscale_ip

        args = [ssh_bin]

        # Use managed key if exists
        if HOST_KEY_PATH.exists():
            args.extend(["-i", str(HOST_KEY_PATH)])
            logger.debug("using_managed_key", key=str(HOST_KEY_PATH))

        # Port
        if port:
            args.extend(["-p", str(port)])

        # Host
        args.append(target)

        # Remote command
        if command:
            args.extend(command)

        logger.info("exec_classic_ssh", args=args)

        # Run SSH (passthrough stdin/stdout/stderr for interactive)
        proc = subprocess.run(args, check=False)

        return proc.returncode
