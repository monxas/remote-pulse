"""Tests for agent signature verification."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_trust_from_enrollment():
    """Test initializing trust from enrollment response."""
    from rp.signature import ServerTrust

    with tempfile.TemporaryDirectory() as tmpdir:
        trust_dir = Path(tmpdir)
        ServerTrust.TRUST_DIR = trust_dir
        ServerTrust.PUBKEY_PATH = trust_dir / "server_pubkey.pem"
        ServerTrust.TRUST_CONFIG_PATH = trust_dir / "server_trust.toml"

        # Mock enrollment data
        pubkey_pem = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lP/bUTNfBNn+DYs3c5i9Y8c=
-----END PUBLIC KEY-----"""
        fingerprint = "SHA256:test123abc"

        # Create trust (return value not needed; we check side-effects below)
        ServerTrust.from_enrollment(pubkey_pem, fingerprint)

        # Verify files created
        assert ServerTrust.PUBKEY_PATH.exists()
        assert ServerTrust.TRUST_CONFIG_PATH.exists()

        # Verify content
        saved_pubkey = ServerTrust.PUBKEY_PATH.read_text()
        assert pubkey_pem in saved_pubkey

        # Load trust back
        loaded_trust = ServerTrust.load()
        assert loaded_trust is not None
        assert loaded_trust.fingerprint == fingerprint


def test_verify_valid_signature():
    """Test verifying a valid signature."""
    from rp.signature import ServerTrust

    # Generate a real Ed25519 keypair for testing
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import hashlib
    import json
    from base64 import b64encode

    with tempfile.TemporaryDirectory() as tmpdir:
        trust_dir = Path(tmpdir)
        ServerTrust.TRUST_DIR = trust_dir
        ServerTrust.PUBKEY_PATH = trust_dir / "server_pubkey.pem"
        ServerTrust.TRUST_CONFIG_PATH = trust_dir / "server_trust.toml"

        # Generate keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Get PEM
        pubkey_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

        # Compute fingerprint
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        digest = hashlib.sha256(public_bytes).digest()
        fingerprint = f"SHA256:{b64encode(digest).decode('ascii').rstrip('=')}"

        # Initialize trust
        trust = ServerTrust.from_enrollment(pubkey_pem, fingerprint)

        # Create and sign a command (mimicking server)
        command_id = "test-123"
        command_type = "exec_shell"
        payload = {"cmd": "echo hello"}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expires_iso = expires_at.isoformat()
        blob = f"{command_id}|{command_type}|{canonical_payload}|{expires_iso}"
        blob_hash = hashlib.sha256(blob.encode("utf-8")).digest()

        signature_bytes = private_key.sign(blob_hash)
        signature_b64 = b64encode(signature_bytes).decode("ascii")

        # Verify
        assert trust.verify_command(
            command_id, command_type, payload, expires_at, signature_b64
        )


def test_verify_tampered_payload():
    """Test that tampered payload fails verification."""
    from rp.signature import ServerTrust
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import hashlib
    import json
    from base64 import b64encode

    with tempfile.TemporaryDirectory() as tmpdir:
        trust_dir = Path(tmpdir)
        ServerTrust.TRUST_DIR = trust_dir
        ServerTrust.PUBKEY_PATH = trust_dir / "server_pubkey.pem"
        ServerTrust.TRUST_CONFIG_PATH = trust_dir / "server_trust.toml"

        # Generate keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        pubkey_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        digest = hashlib.sha256(public_bytes).digest()
        fingerprint = f"SHA256:{b64encode(digest).decode('ascii').rstrip('=')}"

        trust = ServerTrust.from_enrollment(pubkey_pem, fingerprint)

        # Sign original payload
        command_id = "test-456"
        command_type = "exec_shell"
        original_payload = {"cmd": "echo hello"}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        canonical = json.dumps(original_payload, sort_keys=True, separators=(",", ":"))
        blob = f"{command_id}|{command_type}|{canonical}|{expires_at.isoformat()}"
        blob_hash = hashlib.sha256(blob.encode("utf-8")).digest()
        signature_b64 = b64encode(private_key.sign(blob_hash)).decode("ascii")

        # Verify with tampered payload
        tampered_payload = {"cmd": "rm -rf /"}
        assert not trust.verify_command(
            command_id, command_type, tampered_payload, expires_at, signature_b64
        )


def test_verify_expired_command():
    """Test that expired command fails verification."""
    from rp.signature import ServerTrust
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import hashlib
    import json
    from base64 import b64encode

    with tempfile.TemporaryDirectory() as tmpdir:
        trust_dir = Path(tmpdir)
        ServerTrust.TRUST_DIR = trust_dir
        ServerTrust.PUBKEY_PATH = trust_dir / "server_pubkey.pem"
        ServerTrust.TRUST_CONFIG_PATH = trust_dir / "server_trust.toml"

        # Generate keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        pubkey_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        digest = hashlib.sha256(public_bytes).digest()
        fingerprint = f"SHA256:{b64encode(digest).decode('ascii').rstrip('=')}"

        trust = ServerTrust.from_enrollment(pubkey_pem, fingerprint)

        # Sign with expiration in the past
        command_id = "test-789"
        command_type = "exec_shell"
        payload = {"cmd": "echo hello"}
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)  # Expired

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        blob = f"{command_id}|{command_type}|{canonical}|{expires_at.isoformat()}"
        blob_hash = hashlib.sha256(blob.encode("utf-8")).digest()
        signature_b64 = b64encode(private_key.sign(blob_hash)).decode("ascii")

        # Should fail due to expiration
        assert not trust.verify_command(
            command_id, command_type, payload, expires_at, signature_b64
        )


def test_load_missing_trust():
    """Test loading when no trust anchor exists."""
    from rp.signature import ServerTrust

    with tempfile.TemporaryDirectory() as tmpdir:
        trust_dir = Path(tmpdir)
        ServerTrust.TRUST_DIR = trust_dir
        ServerTrust.PUBKEY_PATH = trust_dir / "server_pubkey.pem"
        ServerTrust.CONFIG_PATH = trust_dir / "server_trust.toml"

        # Should return None when files don't exist
        trust = ServerTrust.load()
        assert trust is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
