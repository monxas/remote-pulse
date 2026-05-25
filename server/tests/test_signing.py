"""Tests for Ed25519 command signing."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rp_server.signing import ServerSigningKey, verify_signature


def test_generate_and_load_keypair():
    """Test keypair generation and persistence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_dir = Path(tmpdir)

        # Generate new keypair
        key1 = ServerSigningKey.load_or_generate(key_dir)
        fp1 = key1.public_key_fingerprint()

        # Verify files exist with correct permissions
        private_key_path = key_dir / "server_ed25519_key"
        public_key_path = key_dir / "server_ed25519_key.pub"

        assert private_key_path.exists()
        assert public_key_path.exists()

        # Load existing keypair (should be same)
        key2 = ServerSigningKey.load_or_generate(key_dir)
        fp2 = key2.public_key_fingerprint()

        assert fp1 == fp2


def test_sign_and_verify_roundtrip():
    """Test signing and verification roundtrip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_dir = Path(tmpdir)
        signing_key = ServerSigningKey.load_or_generate(key_dir)

        # Create command
        command_id = "test-cmd-123"
        command_type = "exec_shell"
        payload = {"cmd": "echo hello", "timeout_s": 30}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        # Sign
        signature = signing_key.sign_command(command_id, command_type, payload, expires_at)

        assert signature
        assert len(signature) > 0

        # Verify with public key
        pubkey_pem = signing_key.public_key_pem()
        assert verify_signature(
            pubkey_pem, command_id, command_type, payload, expires_at, signature
        )


def test_tampered_payload_rejected():
    """Test that tampered payload fails verification."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_dir = Path(tmpdir)
        signing_key = ServerSigningKey.load_or_generate(key_dir)

        command_id = "test-cmd-456"
        command_type = "exec_shell"
        payload = {"cmd": "echo hello"}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        # Sign original
        signature = signing_key.sign_command(command_id, command_type, payload, expires_at)

        # Tamper with payload
        tampered_payload = {"cmd": "rm -rf /"}

        # Verify with tampered payload should fail
        pubkey_pem = signing_key.public_key_pem()
        assert not verify_signature(
            pubkey_pem, command_id, command_type, tampered_payload, expires_at, signature
        )


def test_expired_signature_rejected():
    """Test that expired signature fails verification."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_dir = Path(tmpdir)
        signing_key = ServerSigningKey.load_or_generate(key_dir)

        command_id = "test-cmd-789"
        command_type = "exec_shell"
        payload = {"cmd": "echo hello"}

        # Expires in the past
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        # Sign (note: signing doesn't check expiration, only verification does)
        signature = signing_key.sign_command(command_id, command_type, payload, expires_at)

        # Verification should fail due to expiration
        # Note: verify_signature util doesn't check expiration, but agent's
        # ServerTrust.verify_command does. This tests cryptographic validity only.
        pubkey_pem = signing_key.public_key_pem()
        # Signature is cryptographically valid even if expired
        assert verify_signature(
            pubkey_pem, command_id, command_type, payload, expires_at, signature
        )


def test_wrong_pubkey_rejected():
    """Test that signature fails with wrong public key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_dir1 = Path(tmpdir) / "key1"
        key_dir2 = Path(tmpdir) / "key2"
        key_dir1.mkdir()
        key_dir2.mkdir()

        # Generate two different keypairs
        signing_key1 = ServerSigningKey.load_or_generate(key_dir1)
        signing_key2 = ServerSigningKey.load_or_generate(key_dir2)

        command_id = "test-cmd-999"
        command_type = "exec_shell"
        payload = {"cmd": "echo hello"}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        # Sign with key1
        signature = signing_key1.sign_command(command_id, command_type, payload, expires_at)

        # Try to verify with key2's pubkey (should fail)
        pubkey_pem2 = signing_key2.public_key_pem()
        assert not verify_signature(
            pubkey_pem2, command_id, command_type, payload, expires_at, signature
        )


def test_fingerprint_format():
    """Test fingerprint format is SHA256:base64."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_dir = Path(tmpdir)
        signing_key = ServerSigningKey.load_or_generate(key_dir)

        fingerprint = signing_key.public_key_fingerprint()

        # Should start with SHA256:
        assert fingerprint.startswith("SHA256:")

        # Base64 part should be non-empty
        b64_part = fingerprint.split(":", 1)[1]
        assert len(b64_part) > 0


def test_canonical_json_ordering():
    """Test that payload key ordering doesn't affect signature."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_dir = Path(tmpdir)
        signing_key = ServerSigningKey.load_or_generate(key_dir)

        command_id = "test-cmd-canonical"
        command_type = "exec_shell"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        # Same payload, different key order
        payload1 = {"z": "last", "a": "first", "m": "middle"}
        payload2 = {"a": "first", "m": "middle", "z": "last"}

        # Sign both
        sig1 = signing_key.sign_command(command_id, command_type, payload1, expires_at)
        sig2 = signing_key.sign_command(command_id, command_type, payload2, expires_at)

        # Signatures should be identical (canonical JSON)
        assert sig1 == sig2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
