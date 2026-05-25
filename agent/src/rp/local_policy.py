"""Local policy enforcement for remote commands.

Defense-in-depth layer: even with valid server signature, agent
consults local flags/whitelists before executing commands.

Mitigates server compromise (ADR-0008 review C3).
"""

import time
from enum import StrEnum
from pathlib import Path
from typing import Optional
import fnmatch
import structlog

logger = structlog.get_logger()


class CommandDecision(StrEnum):
    """Decision outcome for command evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"  # Telegram approval flow


class LocalPolicy:
    """Local policy engine for command authorization.

    Evaluates commands against local flags, whitelists, and group policies.
    """

    POLICY_DIR = Path("/etc/rp")

    def __init__(self, policy_dir: Optional[Path] = None):
        """Initialize policy engine.

        Args:
            policy_dir: Override policy directory (for testing)
        """
        self.policy_dir = policy_dir or self.POLICY_DIR

    def evaluate(
        self, command_type: str, payload: dict, group: str
    ) -> tuple[CommandDecision, str]:
        """Evaluate command against local policy.

        Args:
            command_type: Command type (exec_shell, pkg_install, etc.)
            payload: Command payload dict
            group: Host group (prod/iarq/family/default)

        Returns:
            Tuple of (decision, reason) where reason is human-readable
        """
        # Normalize group to determine policy tier
        is_sensitive_group = group in ("prod", "iarq")

        logger.debug(
            "evaluating command",
            command_type=command_type,
            group=group,
            sensitive=is_sensitive_group,
        )

        # Route to appropriate handler
        if command_type == "exec_shell":
            return self._eval_exec_shell(is_sensitive_group)
        elif command_type == "pkg_install":
            return self._eval_pkg_install(is_sensitive_group)
        elif command_type == "service_restart":
            return self._eval_service_restart(payload, is_sensitive_group)
        elif command_type == "file_read":
            return self._eval_file_read(payload, is_sensitive_group)
        elif command_type == "file_write":
            return self._eval_file_write(payload, is_sensitive_group)
        elif command_type == "screen_open":
            return self._eval_screen_open()
        elif command_type == "ssh_keys_sync":
            return self._eval_ssh_keys_sync(payload)
        elif command_type == "agent_upgrade":
            return self._eval_agent_upgrade(payload)
        elif command_type == "reboot":
            return self._eval_reboot(is_sensitive_group)
        else:
            # Default-deny for unknown commands
            return (
                CommandDecision.DENY,
                f"unknown command type: {command_type} (default-deny)",
            )

    def _eval_exec_shell(self, is_sensitive: bool) -> tuple[CommandDecision, str]:
        """Evaluate exec_shell command."""
        if not is_sensitive:
            return (CommandDecision.ALLOW, "exec allowed for non-sensitive group")

        # Sensitive groups require flag
        flag = self.policy_dir / "allow-remote-exec"
        if not flag.exists():
            return (
                CommandDecision.DENY,
                "exec denied: /etc/rp/allow-remote-exec flag missing (run: rp local allow-exec)",
            )

        # Check TTL (24h default)
        if self._is_flag_expired(flag, ttl_hours=24):
            return (
                CommandDecision.DENY,
                "exec denied: allow-remote-exec flag expired (>24h old)",
            )

        return (CommandDecision.ALLOW, "exec allowed by flag")

    def _eval_pkg_install(self, is_sensitive: bool) -> tuple[CommandDecision, str]:
        """Evaluate pkg_install command."""
        if is_sensitive:
            return (
                CommandDecision.REQUIRE_APPROVAL,
                "pkg_install requires Telegram approval for sensitive groups",
            )

        return (CommandDecision.ALLOW, "pkg_install allowed for non-sensitive group")

    def _eval_service_restart(
        self, payload: dict, is_sensitive: bool
    ) -> tuple[CommandDecision, str]:
        """Evaluate service_restart command."""
        service_name = payload.get("service_name", "")

        if not is_sensitive:
            return (
                CommandDecision.ALLOW,
                f"service_restart allowed for non-sensitive group: {service_name}",
            )

        # Check whitelist
        whitelist = self.policy_dir / "restart-whitelist"
        if not whitelist.exists():
            return (
                CommandDecision.DENY,
                f"service_restart denied: {service_name} not in whitelist (file missing)",
            )

        allowed_services = self._read_lines(whitelist)
        if self._matches_any_pattern(service_name, allowed_services):
            return (
                CommandDecision.ALLOW,
                f"service_restart allowed: {service_name} in whitelist",
            )

        return (
            CommandDecision.DENY,
            f"service_restart denied: {service_name} not in /etc/rp/restart-whitelist",
        )

    def _eval_file_read(
        self, payload: dict, is_sensitive: bool
    ) -> tuple[CommandDecision, str]:
        """Evaluate file_read command."""
        path = payload.get("path", "")

        if not is_sensitive:
            return (
                CommandDecision.ALLOW,
                f"file_read allowed for non-sensitive group: {path}",
            )

        # Check allowlist
        allowlist = self.policy_dir / "read-allowlist"
        if not allowlist.exists():
            return (
                CommandDecision.DENY,
                f"file_read denied: {path} not in allowlist (file missing)",
            )

        patterns = self._read_lines(allowlist)
        if self._matches_any_pattern(path, patterns):
            return (
                CommandDecision.ALLOW,
                f"file_read allowed: {path} matches allowlist",
            )

        return (
            CommandDecision.DENY,
            f"file_read denied: {path} not in /etc/rp/read-allowlist",
        )

    def _eval_file_write(
        self, payload: dict, is_sensitive: bool
    ) -> tuple[CommandDecision, str]:
        """Evaluate file_write command."""
        path = payload.get("path", "")

        if is_sensitive:
            # Check flag
            flag = self.policy_dir / "allow-remote-write"
            if not flag.exists():
                return (
                    CommandDecision.DENY,
                    "file_write denied: /etc/rp/allow-remote-write flag missing",
                )

            if self._is_flag_expired(flag, ttl_hours=24):
                return (
                    CommandDecision.DENY,
                    "file_write denied: allow-remote-write flag expired",
                )

        # Check path restrictions (both sensitive and non-sensitive)
        safe_prefixes = ("/etc/rp/", "/opt/rp/")
        if not any(path.startswith(prefix) for prefix in safe_prefixes):
            return (
                CommandDecision.REQUIRE_APPROVAL,
                f"file_write requires approval: {path} outside /etc/rp/ or /opt/rp/",
            )

        group_label = "sensitive" if is_sensitive else "non-sensitive"
        return (
            CommandDecision.ALLOW,
            f"file_write allowed for {group_label} group: {path}",
        )

    def _eval_screen_open(self) -> tuple[CommandDecision, str]:
        """Evaluate screen_open command."""
        return (CommandDecision.ALLOW, "screen_open always allowed (display-only)")

    def _eval_ssh_keys_sync(self, payload: dict) -> tuple[CommandDecision, str]:
        """Evaluate ssh_keys_sync command."""
        # Verify groups.yml SHA256 signature
        claimed_sha = payload.get("groups_yml_sha256", "")
        stored_sha_file = self.policy_dir / "groups-yml-sha256"

        if not stored_sha_file.exists():
            return (
                CommandDecision.DENY,
                "ssh_keys_sync denied: no stored groups.yml SHA256 reference",
            )

        stored_sha = stored_sha_file.read_text().strip()
        if claimed_sha != stored_sha:
            return (
                CommandDecision.DENY,
                f"ssh_keys_sync denied: SHA256 mismatch (expected {stored_sha[:8]}..., got {claimed_sha[:8]}...)",
            )

        return (CommandDecision.ALLOW, "ssh_keys_sync allowed: SHA256 verified")

    def _eval_agent_upgrade(self, payload: dict) -> tuple[CommandDecision, str]:
        """Evaluate agent_upgrade command."""
        from rp import __version__

        current_version = __version__
        target_version = payload.get("version", "")

        # Parse semver (simple major.minor check)
        try:
            current_major = int(current_version.split(".")[0])
            target_major = int(target_version.split(".")[0])

            if target_major != current_major:
                return (
                    CommandDecision.REQUIRE_APPROVAL,
                    f"agent_upgrade requires approval: major version change {current_version} -> {target_version}",
                )

        except (ValueError, IndexError):
            return (
                CommandDecision.DENY,
                f"agent_upgrade denied: invalid version format (current={current_version}, target={target_version})",
            )

        return (
            CommandDecision.ALLOW,
            f"agent_upgrade allowed: minor bump to {target_version}",
        )

    def _eval_reboot(self, is_sensitive: bool) -> tuple[CommandDecision, str]:
        """Evaluate reboot command."""
        if is_sensitive:
            return (
                CommandDecision.REQUIRE_APPROVAL,
                "reboot requires Telegram approval for sensitive groups (double-confirm)",
            )

        return (
            CommandDecision.REQUIRE_APPROVAL,
            "reboot requires approval (single confirm for non-sensitive)",
        )

    # Helper methods

    def _is_flag_expired(self, flag_path: Path, ttl_hours: int = 24) -> bool:
        """Check if flag file has expired based on mtime.

        Args:
            flag_path: Path to flag file
            ttl_hours: TTL in hours

        Returns:
            True if expired
        """
        try:
            mtime = flag_path.stat().st_mtime
            age_seconds = time.time() - mtime
            return age_seconds > (ttl_hours * 3600)
        except OSError:
            return True  # Treat stat errors as expired

    def _read_lines(self, file_path: Path) -> list[str]:
        """Read non-empty, non-comment lines from file.

        Args:
            file_path: Path to file

        Returns:
            List of lines (stripped, no comments)
        """
        try:
            lines = file_path.read_text().splitlines()
            return [
                line.strip()
                for line in lines
                if line.strip() and not line.strip().startswith("#")
            ]
        except OSError as e:
            logger.warning("failed to read file", path=str(file_path), error=str(e))
            return []

    def _matches_any_pattern(self, value: str, patterns: list[str]) -> bool:
        """Check if value matches any glob pattern.

        Args:
            value: String to match
            patterns: List of glob patterns

        Returns:
            True if any pattern matches
        """
        return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)


class TelegramApprovalRequest:
    """Placeholder for Telegram approval flow (TODO F4-6)."""

    def __init__(self, command_id: str, command_type: str, reason: str):
        """Initialize approval request.

        Args:
            command_id: Unique command ID
            command_type: Type of command
            reason: Human-readable reason for approval
        """
        self.command_id = command_id
        self.command_type = command_type
        self.reason = reason

    async def wait_for_decision(self, timeout_s: int = 300) -> bool:
        """Wait for Telegram approval decision.

        Args:
            timeout_s: Timeout in seconds (default 5min)

        Returns:
            True if approved, False if rejected/timeout

        Raises:
            NotImplementedError: Will be implemented in F4-6
        """
        raise NotImplementedError(
            "Telegram approval flow not yet implemented (ticket F4-6)"
        )


# Policy file management helpers


def ensure_policy_dir(policy_dir: Optional[Path] = None) -> Path:
    """Ensure policy directory exists.

    Args:
        policy_dir: Override directory (default /etc/rp)

    Returns:
        Path to policy directory
    """
    directory = policy_dir or LocalPolicy.POLICY_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def touch_flag(
    flag_name: str, policy_dir: Optional[Path] = None, ttl_hours: Optional[int] = None
) -> Path:
    """Touch a flag file (create or update mtime).

    Args:
        flag_name: Flag file name (e.g., 'allow-remote-exec')
        policy_dir: Override directory
        ttl_hours: Optional TTL for reference (not enforced here)

    Returns:
        Path to flag file
    """
    directory = ensure_policy_dir(policy_dir)
    flag_path = directory / flag_name
    flag_path.touch()

    logger.info("flag touched", flag=flag_name, ttl_hours=ttl_hours)
    return flag_path


def remove_flag(flag_name: str, policy_dir: Optional[Path] = None) -> bool:
    """Remove a flag file.

    Args:
        flag_name: Flag file name
        policy_dir: Override directory

    Returns:
        True if file was removed, False if didn't exist
    """
    directory = policy_dir or LocalPolicy.POLICY_DIR
    flag_path = directory / flag_name

    if flag_path.exists():
        flag_path.unlink()
        logger.info("flag removed", flag=flag_name)
        return True

    return False


def add_to_whitelist(
    whitelist_name: str, item: str, policy_dir: Optional[Path] = None
) -> None:
    """Add item to whitelist file.

    Args:
        whitelist_name: Whitelist file name (e.g., 'restart-whitelist')
        item: Item to add (service name, glob pattern, etc.)
        policy_dir: Override directory
    """
    directory = ensure_policy_dir(policy_dir)
    whitelist_path = directory / whitelist_name

    existing = set()
    if whitelist_path.exists():
        existing = set(whitelist_path.read_text().splitlines())

    if item not in existing:
        existing.add(item)
        whitelist_path.write_text("\n".join(sorted(existing)) + "\n")
        logger.info("item added to whitelist", whitelist=whitelist_name, item=item)
    else:
        logger.debug("item already in whitelist", whitelist=whitelist_name, item=item)


def remove_from_whitelist(
    whitelist_name: str, item: str, policy_dir: Optional[Path] = None
) -> bool:
    """Remove item from whitelist file.

    Args:
        whitelist_name: Whitelist file name
        item: Item to remove
        policy_dir: Override directory

    Returns:
        True if item was removed, False if not found
    """
    directory = policy_dir or LocalPolicy.POLICY_DIR
    whitelist_path = directory / whitelist_name

    if not whitelist_path.exists():
        return False

    existing = set(whitelist_path.read_text().splitlines())
    if item in existing:
        existing.remove(item)
        whitelist_path.write_text("\n".join(sorted(existing)) + "\n")
        logger.info("item removed from whitelist", whitelist=whitelist_name, item=item)
        return True

    return False


def show_whitelist(whitelist_name: str, policy_dir: Optional[Path] = None) -> list[str]:
    """Show whitelist contents.

    Args:
        whitelist_name: Whitelist file name
        policy_dir: Override directory

    Returns:
        List of whitelist items
    """
    directory = policy_dir or LocalPolicy.POLICY_DIR
    whitelist_path = directory / whitelist_name

    if not whitelist_path.exists():
        return []

    return [
        line.strip()
        for line in whitelist_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def get_flag_status(flag_name: str, policy_dir: Optional[Path] = None) -> dict:
    """Get flag file status.

    Args:
        flag_name: Flag file name
        policy_dir: Override directory

    Returns:
        Dict with exists, mtime, age_hours, expired (24h TTL)
    """
    directory = policy_dir or LocalPolicy.POLICY_DIR
    flag_path = directory / flag_name

    if not flag_path.exists():
        return {"exists": False}

    stat = flag_path.stat()
    age_seconds = time.time() - stat.st_mtime
    age_hours = age_seconds / 3600

    return {
        "exists": True,
        "mtime": stat.st_mtime,
        "age_hours": age_hours,
        "expired": age_hours > 24,
    }
