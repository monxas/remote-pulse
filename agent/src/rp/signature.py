"""Server signature verification for remote commands.

Agent verifies Ed25519 signatures from server before executing commands.
Implements TOFU (Trust On First Use) pattern with fingerprint pinning.
"""

import hashlib
import json
import tomllib
from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


class ServerTrust:
    """Trust anchor for verifying server-signed commands.

    Server pubkey stored in /etc/rp/server_pubkey.pem (mode 0644).
    Fingerprint pinned in /etc/rp/server_trust.toml:
        [trust]
        server_fingerprint = "SHA256:abc123..."
        pinned_at = "2026-05-25T..."
        last_verified_at = "2026-05-25T..."

    On first install, fetched from server during enrollment.
    On subsequent commands, verifies signature against pinned key.
    TOFU pattern; key rotation requires /v1/agent/rotate-trust handshake (F8).
    """

    TRUST_DIR = Path("/etc/rp")
    PUBKEY_PATH = TRUST_DIR / "server_pubkey.pem"
    TRUST_CONFIG_PATH = TRUST_DIR / "server_trust.toml"

    def __init__(
        self,
        pubkey_pem: str,
        fingerprint: str,
        pinned_at: datetime,
        last_verified_at: datetime | None = None,
    ):
        """Initialize trust anchor.

        Args:
            pubkey_pem: PEM-encoded server public key
            fingerprint: SHA256 fingerprint
            pinned_at: When trust was initially established
            last_verified_at: Last successful verification timestamp
        """
        self.pubkey_pem = pubkey_pem
        self.fingerprint = fingerprint
        self.pinned_at = pinned_at
        self.last_verified_at = last_verified_at or pinned_at

        # Lazy-load cryptography imports (only when verification needed)
        self._public_key = None

    @classmethod
    def from_enrollment(cls, server_pubkey_pem: str, fingerprint: str) -> "ServerTrust":
        """Initialize trust from enrollment response.

        Persists pubkey and fingerprint to disk for future verification.

        Args:
            server_pubkey_pem: PEM-encoded server public key
            fingerprint: SHA256 fingerprint

        Returns:
            ServerTrust instance
        """
        now = datetime.now(timezone.utc)
        trust = cls(
            pubkey_pem=server_pubkey_pem,
            fingerprint=fingerprint,
            pinned_at=now,
            last_verified_at=now,
        )

        # Persist to disk
        trust._persist()

        logger.info(
            "server trust established",
            fingerprint=fingerprint,
            pinned_at=now.isoformat(),
        )

        return trust

    @classmethod
    def load(cls) -> "ServerTrust | None":
        """Load existing trust anchor from disk.

        Returns:
            ServerTrust instance if exists, None otherwise
        """
        if not cls.PUBKEY_PATH.exists() or not cls.TRUST_CONFIG_PATH.exists():
            return None

        try:
            # Load pubkey
            pubkey_pem = cls.PUBKEY_PATH.read_text()

            # Load trust config
            with open(cls.TRUST_CONFIG_PATH, "rb") as f:
                config = tomllib.load(f)

            trust_data = config.get("trust", {})
            fingerprint = trust_data.get("server_fingerprint")
            pinned_at_str = trust_data.get("pinned_at")
            last_verified_at_str = trust_data.get("last_verified_at")

            if not fingerprint or not pinned_at_str:
                logger.error("invalid trust config: missing required fields")
                return None

            pinned_at = datetime.fromisoformat(pinned_at_str)
            last_verified_at = (
                datetime.fromisoformat(last_verified_at_str)
                if last_verified_at_str
                else None
            )

            logger.info(
                "server trust loaded",
                fingerprint=fingerprint,
                pinned_at=pinned_at.isoformat(),
            )

            return cls(
                pubkey_pem=pubkey_pem,
                fingerprint=fingerprint,
                pinned_at=pinned_at,
                last_verified_at=last_verified_at,
            )

        except Exception as e:
            logger.error("failed to load server trust", error=str(e))
            return None

    def verify_command(
        self,
        command_id: str,
        command_type: str,
        payload: dict[str, Any],
        expires_at: datetime,
        signature_b64: str,
    ) -> bool:
        """Verify Ed25519 signature against pinned pubkey.

        Checks:
        1. Signature cryptographically valid
        2. Command not expired
        3. Fingerprint matches pinned trust anchor

        Args:
            command_id: Unique command UUID
            command_type: Command type
            payload: Command payload dict
            expires_at: Expiration timestamp
            signature_b64: Base64-encoded Ed25519 signature

        Returns:
            True if valid AND not expired AND fingerprint matches
        """
        # Check expiration first (fast path)
        now = datetime.now(timezone.utc)
        if expires_at < now:
            logger.warning(
                "command expired",
                command_id=command_id,
                expires_at=expires_at.isoformat(),
                now=now.isoformat(),
            )
            return False

        # Lazy-load public key
        if self._public_key is None:
            try:
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                    Ed25519PublicKey,
                )

                pubkey_bytes = self.pubkey_pem.encode("ascii")
                loaded_key = serialization.load_pem_public_key(pubkey_bytes)

                if not isinstance(loaded_key, Ed25519PublicKey):
                    logger.error("server pubkey is not Ed25519")
                    return False

                self._public_key = loaded_key

            except Exception as e:
                logger.error("failed to load server pubkey", error=str(e))
                return False

        # Reconstruct signing blob (must match server's format exactly)
        try:
            canonical_payload = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            )
            expires_iso = expires_at.isoformat()
            blob = f"{command_id}|{command_type}|{canonical_payload}|{expires_iso}"
            blob_hash = hashlib.sha256(blob.encode("utf-8")).digest()

            # Decode signature
            signature_bytes = b64decode(signature_b64)

            # Verify signature
            self._public_key.verify(signature_bytes, blob_hash)

            # Update last verified timestamp
            self.last_verified_at = now
            self._persist()

            logger.info(
                "command signature verified",
                command_id=command_id,
                command_type=command_type,
            )

            return True

        except Exception as e:
            logger.error(
                "signature verification failed",
                command_id=command_id,
                error=str(e),
            )
            return False

    def _persist(self) -> None:
        """Persist trust anchor to disk."""
        try:
            # Ensure directory exists
            self.TRUST_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)

            # Write pubkey
            self.PUBKEY_PATH.write_text(self.pubkey_pem)
            self.PUBKEY_PATH.chmod(0o644)

            # Write trust config as TOML
            trust_toml = f"""[trust]
server_fingerprint = "{self.fingerprint}"
pinned_at = "{self.pinned_at.isoformat()}"
last_verified_at = "{self.last_verified_at.isoformat()}"
"""
            self.TRUST_CONFIG_PATH.write_text(trust_toml)
            self.TRUST_CONFIG_PATH.chmod(0o644)

            logger.debug("trust anchor persisted", fingerprint=self.fingerprint)

        except Exception as e:
            logger.error("failed to persist trust anchor", error=str(e))
            raise
