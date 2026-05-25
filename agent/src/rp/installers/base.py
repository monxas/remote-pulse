"""Shared installer primitives for screen-sharing tools."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# rp-managed config directory (Windows uses ProgramData like rp/config.py).
if sys.platform == "win32":
    RP_CONFIG_DIR = Path("C:/ProgramData/rp")
else:
    RP_CONFIG_DIR = Path("/etc/rp")


class InstallerError(RuntimeError):
    """Raised when an installer step fails irrecoverably."""


@dataclass
class InstallResult:
    """Result of an installer run, surfaced to the CLI layer."""

    tool: str
    installed: bool
    version: Optional[str] = None
    method: Optional[str] = None
    skipped: bool = False
    message: Optional[str] = None
    config_path: Optional[Path] = None
    extras: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """Serializable dict (for logging / capability reporting)."""
        return {
            "tool": self.tool,
            "installed": self.installed,
            "version": self.version,
            "method": self.method,
            "skipped": self.skipped,
            "message": self.message,
            "config_path": str(self.config_path) if self.config_path else None,
            "extras": dict(self.extras),
        }


async def run_subprocess(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: Optional[float] = None,
    env: Optional[dict[str, str]] = None,
) -> tuple[int, str, str]:
    """Run a subprocess with ``shell=False`` and return ``(rc, stdout, stderr)``.

    Args:
        args: Command list (no shell expansion).
        check: Raise :class:`InstallerError` on non-zero exit.
        capture: Capture stdout/stderr; if False, inherits parent streams.
        timeout: Optional timeout in seconds.
        env: Optional env overrides (merged onto ``os.environ``).

    Raises:
        InstallerError: When ``check`` is True and exit code is non-zero, or
            when the executable is missing.
    """
    logger.debug("subprocess_exec", args=args)

    merged_env: Optional[dict[str, str]] = None
    if env is not None:
        merged_env = {**os.environ, **env}

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE if capture else None,
            stderr=asyncio.subprocess.PIPE if capture else None,
            env=merged_env,
        )
    except FileNotFoundError as exc:
        raise InstallerError(f"Executable not found: {args[0]}") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise InstallerError(
            f"Command timed out after {timeout}s: {' '.join(args)}"
        ) from exc

    stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
    stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
    rc = proc.returncode or 0

    if check and rc != 0:
        raise InstallerError(
            f"Command failed ({rc}): {' '.join(args)}\nstderr: {stderr.strip()}"
        )

    return rc, stdout, stderr


def ensure_rp_config_dir() -> Path:
    """Ensure rp-managed config dir exists with secure perms."""
    RP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(RP_CONFIG_DIR, 0o750)
        except PermissionError:
            logger.warning("ensure_rp_config_dir_chmod_denied", path=str(RP_CONFIG_DIR))
    return RP_CONFIG_DIR


def write_secure_toml(path: Path, body: str) -> None:
    """Write a TOML body atomically with mode 0600 on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body)
    if sys.platform != "win32":
        try:
            os.chmod(tmp, 0o600)
        except PermissionError:
            logger.warning("write_secure_toml_chmod_denied", path=str(tmp))
    tmp.replace(path)


def require_root() -> None:
    """Raise :class:`InstallerError` if not running as root/admin on POSIX."""
    if sys.platform == "win32":
        return  # Admin check elsewhere (Windows installers usually elevate).
    try:
        if os.geteuid() != 0:  # type: ignore[attr-defined]
            raise InstallerError("Root privileges required. Re-run with sudo.")
    except AttributeError:
        # Non-POSIX without geteuid; skip.
        return
