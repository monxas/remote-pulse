"""Tests for Telegram approval flow endpoints (F4-6)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select

from rp_server.models import Command, Host


@pytest.fixture
async def test_host(db_session):
    """Create a test host."""
    host = Host(
        hostname="test-host-prod",
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
async def test_command(db_session, test_host):
    """Create a test command pending approval."""
    command = Command(
        host_id=test_host.id,
        issued_by="admin",
        command_type="reboot",
        command_payload={"delay_s": 30},
        server_signature="test-signature",
    )
    db_session.add(command)
    await db_session.commit()
    await db_session.refresh(command)
    return command


class TestRequestApproval:
    """Tests for POST /v1/admin/commands/{command_id}/request-approval."""

    async def test_request_approval_success(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test successful approval request."""
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["command_id"] == str(test_command.id)
        assert "approval_token" in data
        assert "expires_at" in data

        # Verify database updated
        stmt = select(Command).where(Command.id == test_command.id)
        result = await db_session.execute(stmt)
        command = result.scalar_one()

        assert command.approval_token is not None
        assert command.approval_requested_at is not None

    async def test_request_approval_command_not_found(self, client: AsyncClient):
        """Test approval request for non-existent command."""
        fake_id = uuid.uuid4()
        response = await client.post(f"/v1/admin/commands/{fake_id}/request-approval")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"].lower()

    async def test_request_approval_already_requested(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test approval request when already requested."""
        # First request
        await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")

        # Second request should fail
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already requested" in response.json()["detail"].lower()


class TestApproveCommand:
    """Tests for POST /v1/admin/commands/approve/{approval_token}."""

    async def test_approve_command_success(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test successful command approval."""
        # First request approval
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")
        approval_token = response.json()["approval_token"]

        # Then approve
        payload = {"approver_id": "ramonkawa", "reason": "Test approval"}
        response = await client.post(
            f"/v1/admin/commands/approve/{approval_token}",
            json=payload,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "approved"
        assert data["command_id"] == str(test_command.id)

        # Verify database updated
        stmt = select(Command).where(Command.id == test_command.id)
        result = await db_session.execute(stmt)
        command = result.scalar_one()

        assert command.human_approved is True
        assert command.approved_by == "telegram:ramonkawa"
        assert command.approval_responded_at is not None
        assert command.approval_token is None  # Single-use token cleared

    async def test_approve_command_not_found(self, client: AsyncClient):
        """Test approval with invalid token."""
        fake_token = uuid.uuid4()
        payload = {"approver_id": "ramonkawa"}
        response = await client.post(
            f"/v1/admin/commands/approve/{fake_token}",
            json=payload,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_approve_command_expired(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test approval with expired token."""
        # Request approval
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")
        approval_token = response.json()["approval_token"]

        # Manually backdate approval_requested_at to simulate expiration
        stmt = select(Command).where(Command.id == test_command.id)
        result = await db_session.execute(stmt)
        command = result.scalar_one()

        # Set to 6 minutes ago (past 5min TTL)
        command.approval_requested_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        await db_session.commit()

        # Try to approve
        payload = {"approver_id": "ramonkawa"}
        response = await client.post(
            f"/v1/admin/commands/approve/{approval_token}",
            json=payload,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "expired" in response.json()["detail"].lower()

    async def test_approve_command_already_processed(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test approval when command already processed."""
        # Request and approve
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")
        approval_token = response.json()["approval_token"]

        payload = {"approver_id": "ramonkawa"}
        await client.post(f"/v1/admin/commands/approve/{approval_token}", json=payload)

        # Try to approve again (token was cleared)
        response = await client.post(
            f"/v1/admin/commands/approve/{approval_token}",
            json=payload,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRejectCommand:
    """Tests for POST /v1/admin/commands/reject/{approval_token}."""

    async def test_reject_command_success(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test successful command rejection."""
        # Request approval
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")
        approval_token = response.json()["approval_token"]

        # Reject
        payload = {"approver_id": "ramonkawa", "reason": "Not safe"}
        response = await client.post(
            f"/v1/admin/commands/reject/{approval_token}",
            json=payload,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "rejected"

        # Verify database
        stmt = select(Command).where(Command.id == test_command.id)
        result = await db_session.execute(stmt)
        command = result.scalar_one()

        assert command.human_approved is False
        assert "telegram_reject:ramonkawa" in command.rejected_reason
        assert command.approval_token is None

    async def test_reject_command_default_reason(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test rejection with no explicit reason."""
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")
        approval_token = response.json()["approval_token"]

        payload = {"approver_id": "ramonkawa"}  # No reason
        response = await client.post(
            f"/v1/admin/commands/reject/{approval_token}",
            json=payload,
        )

        assert response.status_code == status.HTTP_200_OK

        stmt = select(Command).where(Command.id == test_command.id)
        result = await db_session.execute(stmt)
        command = result.scalar_one()

        assert "rejected by admin via Telegram" in command.rejected_reason


class TestListPendingApprovals:
    """Tests for GET /v1/admin/commands/pending-approval."""

    async def test_list_pending_empty(self, client: AsyncClient):
        """Test listing when no pending approvals."""
        response = await client.get("/v1/admin/commands/pending-approval")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_list_pending_with_items(
        self,
        client: AsyncClient,
        test_command: Command,
    ):
        """Test listing pending approvals."""
        # Request approval
        await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")

        # List pending
        response = await client.get("/v1/admin/commands/pending-approval")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1

        item = data[0]
        assert item["command_id"] == str(test_command.id)
        assert item["command_type"] == "reboot"
        assert item["host_hostname"] == "test-host-prod"
        assert item["host_group"] == "prod"

    async def test_list_pending_excludes_processed(
        self,
        client: AsyncClient,
        db_session,
        test_command: Command,
    ):
        """Test that processed approvals are excluded."""
        # Request and approve
        response = await client.post(f"/v1/admin/commands/{test_command.id}/request-approval")
        approval_token = response.json()["approval_token"]

        payload = {"approver_id": "ramonkawa"}
        await client.post(f"/v1/admin/commands/approve/{approval_token}", json=payload)

        # List should be empty now
        response = await client.get("/v1/admin/commands/pending-approval")
        assert response.json() == []


class TestWebhookIntegration:
    """Tests for webhook integration (mocked)."""

    @patch("rp_server.integrations.telegram_webhook.TelegramApprovalWebhook")
    async def test_webhook_fired_on_request(
        self,
        mock_webhook_class,
        client: AsyncClient,
        test_command: Command,
    ):
        """Test that webhook is fired when approval requested."""
        mock_webhook = AsyncMock()
        mock_webhook_class.return_value = mock_webhook

        # TODO: This test requires integration in commands.py router
        # which calls TelegramApprovalWebhook.fire_approval_request()
        # Placeholder for now, will be implemented when commands.py is updated
        pass
