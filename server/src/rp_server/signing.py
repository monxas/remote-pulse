"""Ed25519 signing for remote commands.

Server signs commands with private key, agents verify with public key.
Implements defense-in-depth: even with valid signature, agents consult
local policy enforcement (ADR-0008 §13).
"""

import hashlib
import json
import structlog
from base64 import b64decode, b64encode
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

logger = structlog.get_logger()


class ServerSigningKey:
    """Ed25519 keypair for signing commands sent to agents.

    Private key stored in /etc/rp/server_ed25519_key (mode 0600, owned by rp user).
    Public key stored in /etc/rp/server_ed25519_key.pub, distributed to agents
    at enrollment time so they can verify command signatures.

    Thread-safe: loads once on init, immutable thereafter.
    """

    def __init__(self, private_key: Ed25519PrivateKey):
        """Initialize with loaded private key.

        Args:
            private_key: Ed25519 private key instance
        """
        self._private_key = private_key
        self._public_key = private_key.public_key()

    @classmethod
    def load_or_generate(cls, key_dir: Path = Path("/etc/rp")) -> "ServerSigningKey":
        """Load existing keypair or generate new one.

        Idempotent: safe to call multiple times, uses existing key if found.

        Args:
            key_dir: Directory for key storage (default /etc/rp)

        Returns:
            ServerSigningKey instance
        """
        key_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

        private_key_path = key_dir / "server_ed25519_key"
        public_key_path = key_dir / "server_ed25519_key.pub"

        # Try loading existing key
        if private_key_path.exists():
            logger.info("loading existing server signing key", path=str(private_key_path))
            try:
                private_pem = private_key_path.read_bytes()
                private_key = serialization.load_pem_private_key(
                    private_pem,
                    password=None,
                )
                if not isinstance(private_key, Ed25519PrivateKey):
                    raise ValueError("Key is not Ed25519")

                logger.info(
                    "server signing key loaded",
                    fingerprint=cls._fingerprint_from_key(private_key.public_key()),
                )
                return cls(private_key)
            except Exception as e:
                logger.error("failed to load signing key, regenerating", error=str(e))
                # Fall through to generation

        # Generate new keypair
        logger.warning("generating new server signing key", path=str(private_key_path))
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Serialize and save
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Write private key with restrictive permissions
        private_key_path.write_bytes(private_pem)
        private_key_path.chmod(0o600)

        # Write public key world-readable
        public_key_path.write_bytes(public_pem)
        public_key_path.chmod(0o644)

        fingerprint = cls._fingerprint_from_key(public_key)
        logger.info(
            "server signing key generated",
            private_key_path=str(private_key_path),
            public_key_path=str(public_key_path),
            fingerprint=fingerprint,
        )

        return cls(private_key)

    def sign_command(
        self,
        command_id: str,
        command_type: str,
        payload: dict[str, Any],
        expires_at: datetime,
    ) -> str:
        """Sign a command payload.

        Creates deterministic signature blob and signs with Ed25519.
        Signed data format: "command_id|command_type|canonical_json|expires_at_iso"

        Args:
            command_id: Unique command UUID
            command_type: Command type (exec_shell, pkg_install, etc.)
            payload: Command payload dict
            expires_at: Expiration timestamp (UTC)

        Returns:
            Base64-encoded Ed25519 signature
        """
        # Create canonical JSON (sorted keys, no whitespace)
        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expires_iso = expires_at.isoformat()

        # Build signing blob
        blob = f"{command_id}|{command_type}|{canonical_payload}|{expires_iso}"
        blob_bytes = blob.encode("utf-8")

        # Hash first (Ed25519 signs 64-byte messages directly, but sha256 ensures
        # deterministic length regardless of payload size)
        blob_hash = hashlib.sha256(blob_bytes).digest()

        # Sign
        signature_bytes = self._private_key.sign(blob_hash)

        # Encode to base64
        signature_b64 = b64encode(signature_bytes).decode("ascii")

        logger.debug(
            "command signed",
            command_id=command_id,
            command_type=command_type,
            expires_at=expires_iso,
        )

        return signature_b64

    def public_key_pem(self) -> str:
        """Return public key as PEM string (for distribution to agents).

        Returns:
            PEM-encoded public key
        """
        public_pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return public_pem.decode("ascii")

    def public_key_fingerprint(self) -> str:
        """Return SHA256 fingerprint of public key.

        Used for trust pinning on agents.

        Returns:
            Fingerprint in format "SHA256:base64..."
        """
        return self._fingerprint_from_key(self._public_key)

    @staticmethod
    def _fingerprint_from_key(public_key: Ed25519PublicKey) -> str:
        """Compute SHA256 fingerprint from public key.

        Args:
            public_key: Ed25519 public key

        Returns:
            Fingerprint in format "SHA256:base64..."
        """
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        digest = hashlib.sha256(public_bytes).digest()
        fingerprint_b64 = b64encode(digest).decode("ascii").rstrip("=")
        return f"SHA256:{fingerprint_b64}"


def verify_signature(
    public_key_pem: str,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
    expires_at: datetime,
    signature_b64: str,
) -> bool:
    """Verify command signature (utility for testing).

    Args:
        public_key_pem: PEM-encoded public key
        command_id: Command UUID
        command_type: Command type
        payload: Command payload
        expires_at: Expiration timestamp
        signature_b64: Base64-encoded signature

    Returns:
        True if signature valid
    """
    try:
        # Load public key
        public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
        if not isinstance(public_key, Ed25519PublicKey):
            return False

        # Reconstruct blob
        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expires_iso = expires_at.isoformat()
        blob = f"{command_id}|{command_type}|{canonical_payload}|{expires_iso}"
        blob_hash = hashlib.sha256(blob.encode("utf-8")).digest()

        # Decode signature
        signature_bytes = b64decode(signature_b64)

        # Verify
        public_key.verify(signature_bytes, blob_hash)
        return True

    except Exception:
        return False
