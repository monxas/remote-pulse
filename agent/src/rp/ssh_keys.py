"""SSH key lifecycle management for Remote-Pulse agent (F4).

Handles local key generation, registration, and authorized_keys synchronization.
"""

import asyncio
import base64
import hashlib
import platform
import tempfile
import uuid
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

RP_CONFIG_DIR = Path("/etc/rp")
HOST_KEY_PATH = RP_CONFIG_DIR / "host_key"
AUTHORIZED_KEYS_DIR = RP_CONFIG_DIR / "authorized_keys.d"
MANAGED_KEYS_PATH = AUTHORIZED_KEYS_DIR / "managed"


def compute_ssh_fingerprint(pubkey: str) -> str:
    """Compute SHA256 fingerprint from SSH pubkey.

    Args:
        pubkey: Full SSH public key (e.g., "ssh-ed25519 AAAA... comment")

    Returns:
        Fingerprint in format "SHA256:base64hash"

    Raises:
        ValueError: If pubkey format invalid
    """
    try:
        parts = pubkey.strip().split()
        if len(parts) < 2:
            raise ValueError("Invalid pubkey format")

        # Decode base64 blob
        blob = base64.b64decode(parts[1])

        # Compute SHA256
        digest = hashlib.sha256(blob).digest()

        # Encode to base64 without padding
        b64 = base64.b64encode(digest).decode("ascii").rstrip("=")

        return f"SHA256:{b64}"
    except Exception as e:
        raise ValueError(f"Failed to compute fingerprint: {e}") from e


async def ensure_host_key() -> tuple[Path, str]:
    """Generate ed25519 host key if it doesn't exist.

    Idempotent. Creates /etc/rp/host_key and host_key.pub.

    Returns:
        Tuple of (pubkey_path, fingerprint)

    Raises:
        RuntimeError: If key generation fails
    """
    # Ensure config directory exists
    RP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if HOST_KEY_PATH.exists():
        logger.info("host_key_exists", path=str(HOST_KEY_PATH))
    else:
        logger.info("generating_host_key", path=str(HOST_KEY_PATH))

        hostname = platform.node()
        comment = f"rp-agent-{hostname}"

        # Run ssh-keygen
        proc = await asyncio.create_subprocess_exec(
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(HOST_KEY_PATH),
            "-N",
            "",
            "-C",
            comment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"ssh-keygen failed: {stderr.decode()}")

        logger.info("host_key_generated", path=str(HOST_KEY_PATH))

    # Read pubkey and compute fingerprint
    pubkey_path = HOST_KEY_PATH.with_suffix(".pub")
    pubkey = pubkey_path.read_text().strip()
    fingerprint = compute_ssh_fingerprint(pubkey)

    return pubkey_path, fingerprint


async def register_key_with_server(
    client: Any,  # RPClient type
    host_id: uuid.UUID,
    pubkey: str,
    fingerprint: str,
    user_name: str = "root",
) -> dict:
    """Register SSH public key with server.

    Args:
        client: RPClient instance
        host_id: Host UUID
        pubkey: SSH public key
        fingerprint: Key fingerprint (SHA256:...)
        user_name: Unix user (default: root)

    Returns:
        Server response dict

    Raises:
        Exception: If registration fails
    """
    logger.info("registering_key", host_id=str(host_id), fingerprint=fingerprint)

    # Detect algorithm from pubkey
    algo = pubkey.split()[0].replace("ssh-", "").split("-")[0]  # ed25519, rsa, ecdsa

    payload = {
        "host_id": str(host_id),
        "user_name": user_name,
        "pubkey": pubkey,
        "fingerprint": fingerprint,
        "algorithm": algo,
    }

    response = await client.post("/v1/keys", json=payload)
    response.raise_for_status()

    logger.info("key_registered", fingerprint=fingerprint)
    return response.json()


async def sync_authorized_keys(client: Any, host_id: uuid.UUID) -> bool:
    """Fetch and sync authorized_keys from server.

    Only writes if content SHA256 differs (idempotent).

    Args:
        client: RPClient instance
        host_id: Host UUID

    Returns:
        True if keys were updated, False if unchanged

    Raises:
        Exception: If sync fails
    """
    logger.info("syncing_authorized_keys", host_id=str(host_id))

    # Fetch from server
    response = await client.get(f"/v1/keys/authorized/{host_id}")
    response.raise_for_status()

    data = response.json()
    new_content = data["content"]
    new_sha256 = data["sha256"]

    # Ensure directory exists
    AUTHORIZED_KEYS_DIR.mkdir(parents=True, exist_ok=True)

    # Check if current content matches
    if MANAGED_KEYS_PATH.exists():
        current_content = MANAGED_KEYS_PATH.read_text()
        current_sha256 = hashlib.sha256(current_content.encode("utf-8")).hexdigest()

        if current_sha256 == new_sha256:
            logger.info("authorized_keys_unchanged", sha256=current_sha256)
            return False

    # Write atomically
    await _atomic_write(MANAGED_KEYS_PATH, new_content)

    logger.info(
        "authorized_keys_updated", sha256=new_sha256, path=str(MANAGED_KEYS_PATH)
    )
    return True


async def _atomic_write(path: Path, content: str) -> None:
    """Write file atomically using temp file + rename.

    Args:
        path: Target file path
        content: Content to write
    """
    # Write to temp file in same directory
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        delete=False,
        prefix=".tmp_",
        suffix=".authorized_keys",
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    # Set permissions (0600)
    tmp_path.chmod(0o600)

    # Atomic rename
    tmp_path.rename(path)


async def configure_sshd_authorized_keys_d() -> bool:
    """Configure sshd to read from /etc/rp/authorized_keys.d/managed.

    Ensures sshd_config has:
        AuthorizedKeysFile .ssh/authorized_keys /etc/rp/authorized_keys.d/managed

    Backs up existing config and reloads sshd if changed.

    Returns:
        True if config was changed, False if unchanged

    Raises:
        RuntimeError: If configuration fails
        PermissionError: If not running as root
    """
    import os

    if os.geteuid() != 0:
        raise PermissionError("configure_sshd requires root privileges")

    sshd_config = Path("/etc/ssh/sshd_config")
    if not sshd_config.exists():
        raise RuntimeError("sshd_config not found")

    logger.info("configuring_sshd", config=str(sshd_config))

    # Read current config
    current_content = sshd_config.read_text()

    # Check if already configured
    target_line = (
        "AuthorizedKeysFile .ssh/authorized_keys /etc/rp/authorized_keys.d/managed"
    )
    if target_line in current_content:
        logger.info("sshd_already_configured")
        return False

    # Backup
    backup_path = sshd_config.with_suffix(".rp-backup")
    if not backup_path.exists():
        backup_path.write_text(current_content)
        logger.info("sshd_config_backed_up", backup=str(backup_path))

    # Add configuration
    new_content = current_content + f"\n\n# Remote-Pulse managed keys\n{target_line}\n"

    # Write atomically
    await _atomic_write(sshd_config, new_content)

    # Reload sshd
    logger.info("reloading_sshd")
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "reload",
        "sshd",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        # Try alternate service name
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "reload",
            "ssh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        if proc.returncode != 0:
            logger.warning("sshd_reload_failed", stderr=stderr.decode())
            raise RuntimeError("Failed to reload sshd")

    logger.info("sshd_configured")
    return True
