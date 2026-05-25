"""Tests for SSH key lifecycle endpoints (F4)."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from rp_server.models import Group, Host, SSHKey
from rp_server.routers.keys import compute_ssh_fingerprint


@pytest.fixture
async def test_host(db_session):
    """Create a test host."""
    host = Host(
        hostname="test-host",
        os="linux",
        arch="x86_64",
        agent_version="0.5.0",
        group_name="prod",
    )
    db_session.add(host)
    await db_session.commit()
    await db_session.refresh(host)
    return host


@pytest.fixture
async def test_group(db_session):
    """Create a test group."""
    group = Group(
        name="prod",
        description="Production group",
        access_users=["ramon@monxas.casa"],
        auto_distribute_keys=True,
    )
    db_session.add(group)
    await db_session.commit()
    return group


# Sample ed25519 pubkey for testing
SAMPLE_PUBKEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl test@example"
)
SAMPLE_FINGERPRINT = "SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco"


class TestComputeFingerprint:
    """Test fingerprint computation."""

    def test_compute_ssh_fingerprint(self):
        """Compute fingerprint from sample pubkey."""
        fp = compute_ssh_fingerprint(SAMPLE_PUBKEY)
        assert fp.startswith("SHA256:")
        assert len(fp) == 50  # SHA256: + 43 base64 chars

    def test_compute_fingerprint_invalid(self):
        """Invalid pubkey raises ValueError."""
        with pytest.raises(ValueError, match="Invalid pubkey format"):
            compute_ssh_fingerprint("invalid")


@pytest.mark.asyncio
class TestRegisterKey:
    """Test POST /v1/keys - register SSH key."""

    async def test_register_key_success(self, client: AsyncClient, test_host, test_group):
        """Register a new SSH key successfully."""
        payload = {
            "host_id": str(test_host.id),
            "user_name": "root",
            "pubkey": SAMPLE_PUBKEY,
            "fingerprint": compute_ssh_fingerprint(SAMPLE_PUBKEY),
            "algorithm": "ed25519",
        }

        response = await client.post("/v1/keys", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["host_id"] == str(test_host.id)
        assert data["fingerprint"] == payload["fingerprint"]
        assert data["revoked_at"] is None

    async def test_register_key_duplicate(
        self, client: AsyncClient, test_host, test_group, db_session
    ):
        """Registering duplicate active key returns 409."""
        # First registration
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
        )
        db_session.add(key)
        await db_session.commit()

        # Attempt duplicate
        payload = {
            "host_id": str(test_host.id),
            "user_name": "root",
            "pubkey": SAMPLE_PUBKEY,
            "fingerprint": compute_ssh_fingerprint(SAMPLE_PUBKEY),
            "algorithm": "ed25519",
        }

        response = await client.post("/v1/keys", json=payload)
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]

    async def test_register_key_fingerprint_mismatch(
        self, client: AsyncClient, test_host, test_group
    ):
        """Invalid fingerprint returns 400."""
        payload = {
            "host_id": str(test_host.id),
            "user_name": "root",
            "pubkey": SAMPLE_PUBKEY,
            "fingerprint": "SHA256:wrongfingerprint1234567890123456789012",
            "algorithm": "ed25519",
        }

        response = await client.post("/v1/keys", json=payload)
        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"].lower()

    async def test_register_key_host_not_found(self, client: AsyncClient, test_group):
        """Registering key for non-existent host returns 404."""
        payload = {
            "host_id": str(uuid.uuid4()),
            "user_name": "root",
            "pubkey": SAMPLE_PUBKEY,
            "fingerprint": compute_ssh_fingerprint(SAMPLE_PUBKEY),
            "algorithm": "ed25519",
        }

        response = await client.post("/v1/keys", json=payload)
        assert response.status_code == 404

    async def test_re_register_revoked_key(
        self, client: AsyncClient, test_host, test_group, db_session
    ):
        """Re-registering a revoked key clears revocation."""
        # Create revoked key
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
            revoked_at=datetime.now(timezone.utc),
            revoked_reason="test revocation",
        )
        db_session.add(key)
        await db_session.commit()

        # Re-register
        payload = {
            "host_id": str(test_host.id),
            "user_name": "root",
            "pubkey": SAMPLE_PUBKEY,
            "fingerprint": compute_ssh_fingerprint(SAMPLE_PUBKEY),
            "algorithm": "ed25519",
        }

        response = await client.post("/v1/keys", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["revoked_at"] is None
        assert data["revoked_reason"] is None


@pytest.mark.asyncio
class TestListKeys:
    """Test GET /v1/keys - list SSH keys."""

    async def test_list_keys(self, client: AsyncClient, test_host, test_group, db_session):
        """List all active keys."""
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
        )
        db_session.add(key)
        await db_session.commit()

        response = await client.get("/v1/keys")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["fingerprint"] == key.fingerprint

    async def test_list_keys_filter_host(
        self, client: AsyncClient, test_host, test_group, db_session
    ):
        """Filter keys by host_id."""
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
        )
        db_session.add(key)
        await db_session.commit()

        response = await client.get(f"/v1/keys?host_id={test_host.id}")
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_list_keys_exclude_revoked(
        self, client: AsyncClient, test_host, test_group, db_session
    ):
        """By default, revoked keys are excluded."""
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
            revoked_at=datetime.now(timezone.utc),
        )
        db_session.add(key)
        await db_session.commit()

        response = await client.get("/v1/keys")
        assert response.status_code == 200
        assert len(response.json()) == 0

    async def test_list_keys_include_revoked(
        self, client: AsyncClient, test_host, test_group, db_session
    ):
        """Include revoked keys with flag."""
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
            revoked_at=datetime.now(timezone.utc),
        )
        db_session.add(key)
        await db_session.commit()

        response = await client.get("/v1/keys?include_revoked=true")
        assert response.status_code == 200
        assert len(response.json()) == 1


@pytest.mark.asyncio
class TestRevokeKey:
    """Test DELETE /v1/keys/{fingerprint} - revoke SSH key."""

    async def test_revoke_key(self, client: AsyncClient, test_host, test_group, db_session):
        """Revoke an active key."""
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
        )
        db_session.add(key)
        await db_session.commit()

        response = await client.delete(f"/v1/keys/{key.fingerprint}?reason=test+revocation")
        assert response.status_code == 200

        data = response.json()
        assert data["revoked_at"] is not None
        assert data["revoked_reason"] == "test revocation"

    async def test_revoke_key_not_found(self, client: AsyncClient):
        """Revoking non-existent key returns 404."""
        response = await client.delete("/v1/keys/SHA256:fakefingerprint?reason=test")
        assert response.status_code == 404

    async def test_revoke_already_revoked(
        self, client: AsyncClient, test_host, test_group, db_session
    ):
        """Revoking already revoked key returns 400."""
        key = SSHKey(
            host_id=test_host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
            revoked_at=datetime.now(timezone.utc),
        )
        db_session.add(key)
        await db_session.commit()

        response = await client.delete(f"/v1/keys/{key.fingerprint}?reason=test")
        assert response.status_code == 400
        assert "already revoked" in response.json()["detail"]


@pytest.mark.asyncio
class TestDistributeKeys:
    """Test POST /v1/keys/distribute/{group} - generate authorized_keys."""

    async def test_distribute_keys(self, client: AsyncClient, test_group, db_session):
        """Distribute keys for a group."""
        # Create hosts in group
        host1 = Host(
            hostname="host1", os="linux", arch="x86_64", agent_version="0.5.0", group_name="prod"
        )
        host2 = Host(
            hostname="host2", os="linux", arch="x86_64", agent_version="0.5.0", group_name="prod"
        )
        db_session.add_all([host1, host2])
        await db_session.commit()
        await db_session.refresh(host1)
        await db_session.refresh(host2)

        # Create keys
        key1 = SSHKey(
            host_id=host1.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
        )
        # Different key for host2
        key2_pubkey = (
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBbXBlZjbZ8W6F9Yj1xCRZcqI5TlJvJ8Xp5A1pR8yO7X host2"
        )
        key2 = SSHKey(
            host_id=host2.id,
            user_name="root",
            pubkey=key2_pubkey,
            fingerprint=compute_ssh_fingerprint(key2_pubkey),
            algorithm="ed25519",
        )
        db_session.add_all([key1, key2])
        await db_session.commit()

        response = await client.post("/v1/keys/distribute/prod")
        assert response.status_code == 200

        data = response.json()
        assert data["group"] == "prod"
        assert data["host_count"] == 2
        assert data["key_count"] == 2
        assert SAMPLE_PUBKEY in data["content"]
        assert key2_pubkey in data["content"]

    async def test_distribute_keys_group_not_found(self, client: AsyncClient):
        """Distributing for non-existent group returns 404."""
        response = await client.post("/v1/keys/distribute/nonexistent")
        assert response.status_code == 404

    async def test_distribute_keys_excludes_revoked(
        self, client: AsyncClient, test_group, db_session
    ):
        """Revoked keys are excluded from distribution."""
        host = Host(
            hostname="host1", os="linux", arch="x86_64", agent_version="0.5.0", group_name="prod"
        )
        db_session.add(host)
        await db_session.commit()
        await db_session.refresh(host)

        # Active key
        key1 = SSHKey(
            host_id=host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
        )
        # Revoked key
        key2_pubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBbXBlZjbZ8W6F9Yj1xCRZcqI5TlJvJ8Xp5A1pR8yO7X revoked"
        key2 = SSHKey(
            host_id=host.id,
            user_name="root",
            pubkey=key2_pubkey,
            fingerprint=compute_ssh_fingerprint(key2_pubkey),
            algorithm="ed25519",
            revoked_at=datetime.now(timezone.utc),
        )
        db_session.add_all([key1, key2])
        await db_session.commit()

        response = await client.post("/v1/keys/distribute/prod")
        assert response.status_code == 200

        data = response.json()
        assert data["key_count"] == 1
        assert SAMPLE_PUBKEY in data["content"]
        assert key2_pubkey not in data["content"]


@pytest.mark.asyncio
class TestGetAuthorizedKeys:
    """Test GET /v1/keys/authorized/{host_id} - get authorized_keys for host."""

    async def test_get_authorized_keys(self, client: AsyncClient, test_group, db_session):
        """Get authorized keys for a host."""
        # Create host
        host = Host(
            hostname="host1", os="linux", arch="x86_64", agent_version="0.5.0", group_name="prod"
        )
        db_session.add(host)
        await db_session.commit()
        await db_session.refresh(host)

        # Create key
        key = SSHKey(
            host_id=host.id,
            user_name="root",
            pubkey=SAMPLE_PUBKEY,
            fingerprint=compute_ssh_fingerprint(SAMPLE_PUBKEY),
            algorithm="ed25519",
        )
        db_session.add(key)
        await db_session.commit()

        response = await client.get(f"/v1/keys/authorized/{host.id}")
        assert response.status_code == 200

        data = response.json()
        assert SAMPLE_PUBKEY in data["content"]
        assert "sha256" in data
        assert len(data["sha256"]) == 64  # hex

    async def test_get_authorized_keys_host_not_found(self, client: AsyncClient):
        """Host not found returns 404."""
        response = await client.get(f"/v1/keys/authorized/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_get_authorized_keys_no_group(self, client: AsyncClient, db_session):
        """Host with no group returns empty keys."""
        host = Host(
            hostname="host1", os="linux", arch="x86_64", agent_version="0.5.0", group_name=None
        )
        db_session.add(host)
        await db_session.commit()
        await db_session.refresh(host)

        response = await client.get(f"/v1/keys/authorized/{host.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["content"] == ""
