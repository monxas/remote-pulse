"""End-to-end test for signed command flow.

Demonstrates:
1. Server generates keypair and signs command
2. Agent receives pubkey during enrollment
3. Agent verifies signature before execution
4. Tampered commands are rejected
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# Add paths for both server and agent modules
sys.path.insert(0, str(Path(__file__).parent.parent / "server" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent" / "src"))

from rp_server.signing import ServerSigningKey
from rp.signature import ServerTrust


def test_e2e_signed_command_valid():
    """Test full flow: server signs, agent verifies valid command."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Server: Generate keypair and sign command
        server_key_dir = Path(tmpdir) / "server"
        server_key_dir.mkdir()

        signing_key = ServerSigningKey.load_or_generate(server_key_dir)

        command_id = "e2e-test-123"
        command_type = "exec_shell"
        payload = {"cmd": "uptime", "timeout_s": 30}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        signature = signing_key.sign_command(command_id, command_type, payload, expires_at)

        # Simulate enrollment: agent receives pubkey
        pubkey_pem = signing_key.public_key_pem()
        fingerprint = signing_key.public_key_fingerprint()

        # Agent: Initialize trust from enrollment
        agent_trust_dir = Path(tmpdir) / "agent"
        agent_trust_dir.mkdir()

        ServerTrust.TRUST_DIR = agent_trust_dir
        ServerTrust.PUBKEY_PATH = agent_trust_dir / "server_pubkey.pem"
        ServerTrust.TRUST_CONFIG_PATH = agent_trust_dir / "server_trust.toml"

        trust = ServerTrust.from_enrollment(pubkey_pem, fingerprint)

        # Agent: Verify command signature
        verified = trust.verify_command(command_id, command_type, payload, expires_at, signature)

        assert verified, "Valid command should be verified"
        print(f"✅ Valid command verified: {command_id}")


def test_e2e_signed_command_tampered():
    """Test that tampered command is rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Server: Sign original command
        server_key_dir = Path(tmpdir) / "server"
        server_key_dir.mkdir()

        signing_key = ServerSigningKey.load_or_generate(server_key_dir)

        command_id = "e2e-test-456"
        command_type = "exec_shell"
        original_payload = {"cmd": "uptime"}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)

        signature = signing_key.sign_command(
            command_id, command_type, original_payload, expires_at
        )

        # Agent: Initialize trust
        agent_trust_dir = Path(tmpdir) / "agent"
        agent_trust_dir.mkdir()

        ServerTrust.TRUST_DIR = agent_trust_dir
        ServerTrust.PUBKEY_PATH = agent_trust_dir / "server_pubkey.pem"
        ServerTrust.TRUST_CONFIG_PATH = agent_trust_dir / "server_trust.toml"

        trust = ServerTrust.from_enrollment(
            signing_key.public_key_pem(),
            signing_key.public_key_fingerprint(),
        )

        # Attacker: Tamper with payload
        tampered_payload = {"cmd": "rm -rf /"}

        # Agent: Verify tampered command (should fail)
        verified = trust.verify_command(
            command_id, command_type, tampered_payload, expires_at, signature
        )

        assert not verified, "Tampered command should be rejected"
        print(f"✅ Tampered command rejected: {command_id}")


def test_e2e_signed_command_expired():
    """Test that expired command is rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Server: Sign command with past expiration
        server_key_dir = Path(tmpdir) / "server"
        server_key_dir.mkdir()

        signing_key = ServerSigningKey.load_or_generate(server_key_dir)

        command_id = "e2e-test-789"
        command_type = "exec_shell"
        payload = {"cmd": "uptime"}
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)  # Already expired

        signature = signing_key.sign_command(command_id, command_type, payload, expires_at)

        # Agent: Initialize trust
        agent_trust_dir = Path(tmpdir) / "agent"
        agent_trust_dir.mkdir()

        ServerTrust.TRUST_DIR = agent_trust_dir
        ServerTrust.PUBKEY_PATH = agent_trust_dir / "server_pubkey.pem"
        ServerTrust.TRUST_CONFIG_PATH = agent_trust_dir / "server_trust.toml"

        trust = ServerTrust.from_enrollment(
            signing_key.public_key_pem(),
            signing_key.public_key_fingerprint(),
        )

        # Agent: Verify expired command (should fail)
        verified = trust.verify_command(command_id, command_type, payload, expires_at, signature)

        assert not verified, "Expired command should be rejected"
        print(f"✅ Expired command rejected: {command_id}")


if __name__ == "__main__":
    import pytest

    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
