"""Tests for SSH key lifecycle (F4)."""

import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rp.ssh_keys import (
    compute_ssh_fingerprint,
    ensure_host_key,
    register_key_with_server,
    sync_authorized_keys,
)

SAMPLE_PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl test@example"


class TestComputeFingerprint:
    """Test fingerprint computation."""

    def test_compute_ssh_fingerprint(self):
        """Compute fingerprint from sample pubkey."""
        fp = compute_ssh_fingerprint(SAMPLE_PUBKEY)
        assert fp.startswith("SHA256:")
        assert len(fp) == 50

    def test_compute_fingerprint_invalid(self):
        """Invalid pubkey raises ValueError."""
        with pytest.raises(ValueError):
            compute_ssh_fingerprint("invalid")


@pytest.mark.asyncio
class TestEnsureHostKey:
    """Test host key generation."""

    async def test_ensure_host_key_generates_new(self):
        """Generate new key if doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "host_key"

            with patch("rp.ssh_keys.HOST_KEY_PATH", key_path):
                with patch("rp.ssh_keys.RP_CONFIG_DIR", Path(tmpdir)):
                    # Mock ssh-keygen
                    with patch("asyncio.create_subprocess_exec") as mock_exec:
                        mock_proc = AsyncMock()
                        mock_proc.communicate.return_value = (b"", b"")
                        mock_proc.returncode = 0
                        mock_exec.return_value = mock_proc

                        # Write sample pubkey
                        pubkey_path = key_path.with_suffix(".pub")
                        pubkey_path.write_text(SAMPLE_PUBKEY)

                        result_path, fingerprint = await ensure_host_key()

                        assert result_path == pubkey_path
                        assert fingerprint.startswith("SHA256:")
                        mock_exec.assert_called_once()

    async def test_ensure_host_key_idempotent(self):
        """Existing key is not regenerated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "host_key"
            key_path.touch()

            pubkey_path = key_path.with_suffix(".pub")
            pubkey_path.write_text(SAMPLE_PUBKEY)

            with patch("rp.ssh_keys.HOST_KEY_PATH", key_path):
                with patch("rp.ssh_keys.RP_CONFIG_DIR", Path(tmpdir)):
                    with patch("asyncio.create_subprocess_exec") as mock_exec:
                        result_path, fingerprint = await ensure_host_key()

                        assert result_path == pubkey_path
                        assert fingerprint.startswith("SHA256:")
                        # ssh-keygen should not be called
                        mock_exec.assert_not_called()


@pytest.mark.asyncio
class TestRegisterKeyWithServer:
    """Test server registration."""

    async def test_register_key_success(self):
        """Register key successfully."""
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": str(uuid.uuid4()),
            "host_id": str(uuid.uuid4()),
            "fingerprint": "SHA256:test",
            "created_at": "2024-01-01T00:00:00Z",
        }
        mock_client.post.return_value = mock_response

        host_id = uuid.uuid4()
        result = await register_key_with_server(
            client=mock_client,
            host_id=host_id,
            pubkey=SAMPLE_PUBKEY,
            fingerprint="SHA256:test",
        )

        assert "id" in result
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/v1/keys"
        assert call_args[1]["json"]["host_id"] == str(host_id)


@pytest.mark.asyncio
class TestSyncAuthorizedKeys:
    """Test authorized_keys synchronization."""

    async def test_sync_authorized_keys_updates(self):
        """Sync updates keys when content differs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            managed_path = Path(tmpdir) / "managed"

            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "content": f"{SAMPLE_PUBKEY}\n",
                "sha256": "abc123",
            }
            mock_client.get.return_value = mock_response

            with patch("rp.ssh_keys.MANAGED_KEYS_PATH", managed_path):
                with patch("rp.ssh_keys.AUTHORIZED_KEYS_DIR", Path(tmpdir)):
                    host_id = uuid.uuid4()
                    changed = await sync_authorized_keys(mock_client, host_id)

                    assert changed is True
                    assert managed_path.exists()
                    assert SAMPLE_PUBKEY in managed_path.read_text()
                    mock_client.get.assert_called_once_with(
                        f"/v1/keys/authorized/{host_id}"
                    )

    async def test_sync_authorized_keys_idempotent(self):
        """Sync is idempotent when content unchanged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            managed_path = Path(tmpdir) / "managed"
            content = f"{SAMPLE_PUBKEY}\n"
            managed_path.write_text(content)

            import hashlib

            sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "content": content,
                "sha256": sha256,
            }
            mock_client.get.return_value = mock_response

            with patch("rp.ssh_keys.MANAGED_KEYS_PATH", managed_path):
                with patch("rp.ssh_keys.AUTHORIZED_KEYS_DIR", Path(tmpdir)):
                    host_id = uuid.uuid4()
                    changed = await sync_authorized_keys(mock_client, host_id)

                    assert changed is False
                    mock_client.get.assert_called_once()
