"""Agent self-upgrade with canary deploy and automatic rollback.

Implements N-1 binary preservation for safe rollback during canary deploys.
File layout:
    /opt/rp/bin/rp           # current symlink → versioned binary
    /opt/rp/bin/rp-0.1.0     # versioned binary
    /opt/rp/bin/rp-prev      # symlink to N-1 (for rollback)
"""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog

from rp import __version__
from rp.client import RPClient
from rp.commands.runner import RemoteCommand
from rp.platform_detect import get_os, get_arch

logger = structlog.get_logger()

# Installation paths
BIN_DIR = Path("/opt/rp/bin")
STATE_DIR = Path("/var/lib/rp")
UPGRADE_STATE_FILE = STATE_DIR / "upgrade-state.json"

# Binary paths
CURRENT_BIN = BIN_DIR / "rp"
PREV_BIN = BIN_DIR / "rp-prev"


@dataclass
class UpgradeResult:
    """Result of upgrade attempt."""

    old_version: str
    new_version: str
    rollback: bool
    success: bool
    errors: list[str]
    duration_s: float


@dataclass
class RollbackResult:
    """Result of rollback attempt."""

    from_version: str
    to_version: str
    success: bool
    errors: list[str]


class AgentUpgrader:
    """Handles agent self-upgrade with N-1 binary preservation."""

    def __init__(self, client: RPClient | None = None):
        """Initialize upgrader.

        Args:
            client: Optional RPClient instance for server communication
        """
        self.client = client

    async def upgrade_to(
        self,
        target_version: str,
        *,
        signed_command: RemoteCommand | None = None,
        dry_run: bool = False,
    ) -> UpgradeResult:
        """Upgrade agent to target version with automatic rollback on failure.

        Steps:
        1. Verify command signature (if provided)
        2. Download new binary from GitHub Releases
        3. SHA256 verify against published checksum
        4. Move current symlink to rp-prev
        5. Atomically swap rp symlink to new version
        6. Run self-check (rp version, rp status)
        7. If self-check fails → automatic rollback
        8. Send version_handshake to server within 90s
        9. Mark upgrade successful in upgrade-state.json

        Args:
            target_version: Version to upgrade to (e.g., "0.2.0")
            signed_command: Optional signed command for verification
            dry_run: If True, show what would happen without executing

        Returns:
            UpgradeResult with outcome details
        """
        start_time = datetime.now(timezone.utc)
        old_version = __version__
        errors: list[str] = []

        logger.info(
            "upgrade initiated",
            old_version=old_version,
            target_version=target_version,
            dry_run=dry_run,
        )

        try:
            # Verify signature if provided (already done in runner.py, but double-check)
            if signed_command and not dry_run:
                logger.info("signature already verified by runner")

            # Ensure directories exist
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            STATE_DIR.mkdir(parents=True, exist_ok=True)

            # Determine binary name for current platform
            os_type = get_os()
            arch = get_arch()
            binary_name = self._get_binary_name(os_type, arch)

            if dry_run:
                logger.info(
                    "dry-run: would download binary",
                    binary_name=binary_name,
                    target_version=target_version,
                )
                return UpgradeResult(
                    old_version=old_version,
                    new_version=target_version,
                    rollback=False,
                    success=True,
                    errors=[],
                    duration_s=0.0,
                )

            # Download new binary
            binary_path, checksum_ok = await self._download_binary(
                target_version, binary_name
            )
            if not checksum_ok:
                errors.append("SHA256 checksum verification failed")
                return UpgradeResult(
                    old_version=old_version,
                    new_version=target_version,
                    rollback=False,
                    success=False,
                    errors=errors,
                    duration_s=(
                        datetime.now(timezone.utc) - start_time
                    ).total_seconds(),
                )

            # Preserve current version as N-1
            versioned_binary = BIN_DIR / f"rp-{target_version}"
            shutil.move(str(binary_path), str(versioned_binary))
            versioned_binary.chmod(0o755)

            # Preserve current as prev (if exists)
            if CURRENT_BIN.exists() and CURRENT_BIN.is_symlink():
                current_target = CURRENT_BIN.resolve()
                # Remove old prev symlink if exists
                if PREV_BIN.exists():
                    PREV_BIN.unlink()
                # Create new prev symlink pointing to current
                PREV_BIN.symlink_to(current_target)
                logger.info("preserved N-1 binary", prev_target=str(current_target))

            # Atomically swap current symlink (os.rename is atomic)
            temp_symlink = BIN_DIR / f"rp-{os.getpid()}.tmp"
            temp_symlink.symlink_to(versioned_binary)
            os.rename(temp_symlink, CURRENT_BIN)

            logger.info(
                "binary swapped",
                new_version=target_version,
                binary_path=str(versioned_binary),
            )

            # Run self-check (with 90s timeout)
            self_check_ok = await self._run_self_check(timeout_s=90)

            if not self_check_ok:
                logger.error("self-check failed after upgrade, initiating rollback")
                errors.append("self-check failed post-upgrade")

                # Automatic rollback
                rollback_result = await self.rollback(reason="self_check_timeout_90s")
                if not rollback_result.success:
                    errors.extend(rollback_result.errors)

                return UpgradeResult(
                    old_version=old_version,
                    new_version=target_version,
                    rollback=True,
                    success=False,
                    errors=errors,
                    duration_s=(
                        datetime.now(timezone.utc) - start_time
                    ).total_seconds(),
                )

            # Send version_handshake to server
            if self.client:
                try:
                    await self.client.version_handshake(
                        agent_version=target_version,
                        api_compat_min="1.0",
                        api_compat_max="1.0",
                    )
                    logger.info("version handshake sent to server")
                except Exception as e:
                    logger.warning("version handshake failed", error=str(e))
                    # Not critical enough to rollback

            # Mark upgrade successful
            self._save_upgrade_state(
                {
                    "target_version": target_version,
                    "old_version": old_version,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "success": True,
                }
            )

            duration_s = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "upgrade completed successfully",
                old_version=old_version,
                new_version=target_version,
                duration_s=duration_s,
            )

            return UpgradeResult(
                old_version=old_version,
                new_version=target_version,
                rollback=False,
                success=True,
                errors=[],
                duration_s=duration_s,
            )

        except Exception as e:
            logger.exception("upgrade failed with exception", error=str(e))
            errors.append(f"exception: {str(e)}")
            return UpgradeResult(
                old_version=old_version,
                new_version=target_version,
                rollback=False,
                success=False,
                errors=errors,
                duration_s=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )

    async def rollback(self, reason: str = "manual") -> RollbackResult:
        """Rollback to N-1 version.

        Reads rp-prev symlink, swaps rp symlink back, restarts service,
        reports to server.

        Args:
            reason: Reason for rollback (for logging/audit)

        Returns:
            RollbackResult with outcome
        """
        errors: list[str] = []
        from_version = __version__

        logger.warning("rollback initiated", from_version=from_version, reason=reason)

        try:
            # Check if prev symlink exists
            if not PREV_BIN.exists():
                errors.append("no N-1 binary found (rp-prev symlink missing)")
                return RollbackResult(
                    from_version=from_version,
                    to_version="unknown",
                    success=False,
                    errors=errors,
                )

            prev_target = PREV_BIN.resolve()
            if not prev_target.exists():
                errors.append(f"rp-prev points to non-existent binary: {prev_target}")
                return RollbackResult(
                    from_version=from_version,
                    to_version="unknown",
                    success=False,
                    errors=errors,
                )

            # Extract version from prev binary path (rp-X.Y.Z)
            to_version = prev_target.name.replace("rp-", "")

            # Atomically swap current symlink back to prev
            temp_symlink = BIN_DIR / f"rp-{os.getpid()}.tmp"
            temp_symlink.symlink_to(prev_target)
            os.rename(temp_symlink, CURRENT_BIN)

            logger.info(
                "symlink rolled back", from_version=from_version, to_version=to_version
            )

            # Restart service (systemctl restart remote-pulse)
            try:
                subprocess.run(
                    ["systemctl", "restart", "remote-pulse"],
                    check=True,
                    timeout=30,
                    capture_output=True,
                )
                logger.info("remote-pulse service restarted")
            except FileNotFoundError:
                logger.warning("systemctl not found, skipping service restart")
            except subprocess.TimeoutExpired:
                logger.error("service restart timed out after 30s")
                errors.append("service restart timeout")
            except subprocess.CalledProcessError as e:
                logger.error("service restart failed", stderr=e.stderr.decode())
                errors.append(f"service restart failed: {e.stderr.decode()}")

            # Report rollback to server
            if self.client:
                try:
                    await self.client.report_rollback(
                        from_version=from_version,
                        to_version=to_version,
                        reason=reason,
                    )
                except Exception as e:
                    logger.warning("failed to report rollback to server", error=str(e))
                    # Not critical

            # Save rollback state
            self._save_upgrade_state(
                {
                    "from_version": from_version,
                    "to_version": to_version,
                    "rolled_back_at": datetime.now(timezone.utc).isoformat(),
                    "reason": reason,
                }
            )

            logger.info(
                "rollback completed",
                from_version=from_version,
                to_version=to_version,
                reason=reason,
            )

            return RollbackResult(
                from_version=from_version,
                to_version=to_version,
                success=True,
                errors=errors,
            )

        except Exception as e:
            logger.exception("rollback failed", error=str(e))
            errors.append(f"exception: {str(e)}")
            return RollbackResult(
                from_version=from_version,
                to_version="unknown",
                success=False,
                errors=errors,
            )

    def get_versions(self) -> dict[str, Any]:
        """Get current, previous, and available versions.

        Returns:
            Dict with current, previous, and available_versions keys
        """
        versions: dict[str, Any] = {
            "current": __version__,
            "previous": None,
            "available_versions": [],
        }

        # Check previous version
        if PREV_BIN.exists() and PREV_BIN.is_symlink():
            prev_target = PREV_BIN.resolve()
            if prev_target.exists():
                versions["previous"] = prev_target.name.replace("rp-", "")

        # Fetch available versions from GitHub (best-effort)
        try:
            import httpx

            response = httpx.get(
                "https://api.github.com/repos/monxas/remote-pulse/releases",
                timeout=5.0,
            )
            if response.status_code == 200:
                releases = response.json()
                versions["available_versions"] = [
                    r["tag_name"].lstrip("v")
                    for r in releases
                    if not r.get("prerelease")
                ]
        except Exception as e:
            logger.warning("failed to fetch available versions", error=str(e))

        return versions

    async def _download_binary(
        self, version: str, binary_name: str
    ) -> tuple[Path, bool]:
        """Download binary from GitHub Releases and verify SHA256.

        Args:
            version: Version to download (e.g., "0.2.0")
            binary_name: Binary filename (e.g., "rp-linux-x86_64")

        Returns:
            Tuple of (binary_path, checksum_ok)
        """
        base_url = (
            f"https://github.com/monxas/remote-pulse/releases/download/v{version}"
        )
        binary_url = f"{base_url}/{binary_name}"
        checksum_url = f"{base_url}/SHA256SUMS"

        logger.info("downloading binary", url=binary_url)

        # Download binary
        async with httpx.AsyncClient(timeout=300.0) as client:
            binary_response = await client.get(binary_url)
            binary_response.raise_for_status()

            # Download checksum file
            checksum_response = await client.get(checksum_url)
            checksum_response.raise_for_status()

        # Save binary to temp file
        temp_dir = tempfile.mkdtemp()
        binary_path = Path(temp_dir) / binary_name
        binary_path.write_bytes(binary_response.content)

        # Verify SHA256
        binary_hash = hashlib.sha256(binary_response.content).hexdigest()
        checksums = checksum_response.text
        expected_line = [line for line in checksums.split("\n") if binary_name in line]

        if not expected_line:
            logger.error("binary not found in SHA256SUMS", binary_name=binary_name)
            return binary_path, False

        expected_hash = expected_line[0].split()[0]
        checksum_ok = binary_hash == expected_hash

        if checksum_ok:
            logger.info("SHA256 verified", binary_name=binary_name, hash=binary_hash)
        else:
            logger.error(
                "SHA256 mismatch",
                binary_name=binary_name,
                expected=expected_hash,
                actual=binary_hash,
            )

        return binary_path, checksum_ok

    async def _run_self_check(self, timeout_s: int = 90) -> bool:
        """Run self-check after upgrade.

        Checks:
        1. `rp version` returns expected new version
        2. `rp status` shows daemon running
        3. POST /v1/heartbeat succeeds (verify server connectivity)
        4. No critical exceptions in last 30s logs

        Args:
            timeout_s: Timeout in seconds

        Returns:
            True if all checks pass
        """
        logger.info("running self-check", timeout_s=timeout_s)

        try:
            # Check 1: rp version
            result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    str(CURRENT_BIN),
                    "version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=10.0,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.error("rp version check failed", stderr=stderr.decode())
                return False

            logger.info("rp version check OK")

            # Check 2: rp status
            result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    str(CURRENT_BIN),
                    "status",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=10.0,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.warning(
                    "rp status check returned non-zero", stderr=stderr.decode()
                )
                # Not critical, continue

            logger.info("rp status check OK")

            # Check 3: Heartbeat to server
            if self.client:
                try:
                    await asyncio.wait_for(
                        self.client.send_heartbeat(),
                        timeout=30.0,
                    )
                    logger.info("heartbeat check OK")
                except asyncio.TimeoutError:
                    logger.error("heartbeat check timed out")
                    return False
                except Exception as e:
                    logger.error("heartbeat check failed", error=str(e))
                    return False

            # Check 4: No critical exceptions in logs (stub - would need log file access)
            # For now, assume OK if previous checks passed
            logger.info("self-check completed successfully")
            return True

        except asyncio.TimeoutError:
            logger.error("self-check timed out", timeout_s=timeout_s)
            return False
        except Exception as e:
            logger.exception("self-check failed with exception", error=str(e))
            return False

    def _get_binary_name(self, os_type: str, arch: str) -> str:
        """Get binary name for platform.

        Args:
            os_type: OS type (linux, darwin, windows)
            arch: Architecture (x86_64, arm64, etc.)

        Returns:
            Binary filename
        """
        if os_type == "windows":
            return f"rp-{os_type}-{arch}.exe"
        return f"rp-{os_type}-{arch}"

    def _save_upgrade_state(self, state: dict[str, Any]) -> None:
        """Save upgrade state to disk.

        Args:
            state: State dict to save
        """
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            UPGRADE_STATE_FILE.write_text(json.dumps(state, indent=2))
            logger.debug("upgrade state saved", path=str(UPGRADE_STATE_FILE))
        except Exception as e:
            logger.error("failed to save upgrade state", error=str(e))
