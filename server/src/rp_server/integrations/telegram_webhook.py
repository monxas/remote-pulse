"""Telegram approval webhook dispatcher for n8n integration.

F4-6: Fires approval request webhooks to n8n workflow which displays
Telegram inline keyboard to admin for approve/reject decision.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog

from rp_server.models import Command, Host

logger = structlog.get_logger()


class TelegramApprovalWebhook:
    """Dispatcher for Telegram approval requests via n8n webhook."""

    def __init__(self, webhook_url: str, server_public_url: str, timeout_s: float = 10.0):
        """Initialize webhook dispatcher.

        Args:
            webhook_url: n8n webhook endpoint URL
            server_public_url: Public server URL for callback endpoints
            timeout_s: HTTP request timeout
        """
        self.webhook_url = webhook_url
        self.server_public_url = server_public_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def fire_approval_request(
        self,
        command: Command,
        host: Host,
        approval_token: uuid.UUID,
        ttl_minutes: int = 5,
    ) -> None:
        """Fire approval request webhook to n8n.

        Sends webhook that triggers Telegram message with inline approve/reject buttons.

        Args:
            command: Command requiring approval
            host: Target host (for hostname display)
            approval_token: Unique approval token
            ttl_minutes: Approval TTL in minutes (default 5)

        Raises:
            httpx.HTTPError: If webhook delivery fails
        """
        now = datetime.now()
        expires_at = now + timedelta(minutes=ttl_minutes)

        payload = {
            "event": "approval_required",
            "command_id": str(command.id),
            "command_type": command.command_type,
            "command_payload": command.command_payload,
            "host_id": str(command.host_id),
            "host_hostname": host.hostname,
            "host_group": host.group_name or "default",
            "issued_by": command.issued_by,
            "issued_at": command.issued_at.isoformat(),
            "approval_token": str(approval_token),
            "approval_url_accept": f"{self.server_public_url}/v1/admin/commands/approve/{approval_token}",
            "approval_url_reject": f"{self.server_public_url}/v1/admin/commands/reject/{approval_token}",
            "expires_at": expires_at.isoformat(),
        }

        logger.info(
            "firing approval webhook",
            command_id=str(command.id),
            command_type=command.command_type,
            host=host.hostname,
            approval_token=str(approval_token),
            ttl_minutes=ttl_minutes,
        )

        try:
            response = await self._client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            logger.info(
                "approval webhook delivered",
                command_id=str(command.id),
                status_code=response.status_code,
            )

        except httpx.HTTPError as e:
            logger.error(
                "approval webhook failed",
                command_id=str(command.id),
                error=str(e),
                webhook_url=self.webhook_url,
            )
            raise

    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()


def build_telegram_message(
    command_type: str,
    payload: dict[str, Any],
    host_hostname: str,
    host_group: str,
    issued_by: str,
    issued_at: datetime,
) -> str:
    """Build human-readable Telegram message for approval request.

    Args:
        command_type: Type of command
        payload: Command payload
        host_hostname: Target host
        host_group: Target host group
        issued_by: User who issued command
        issued_at: When command was issued

    Returns:
        Formatted message string
    """
    # Format payload summary
    payload_str = _format_payload_summary(command_type, payload)

    message = f"""🔐 Remote-Pulse approval needed

Host:    {host_hostname} ({host_group})
Action:  {command_type}
Payload: {payload_str}
Issued:  {issued_by}
When:    {issued_at.strftime("%Y-%m-%d %H:%M:%S UTC")}

Respond within 5 minutes or auto-reject."""

    return message


def _format_payload_summary(command_type: str, payload: dict[str, Any]) -> str:
    """Format payload summary for Telegram message.

    Args:
        command_type: Command type
        payload: Command payload

    Returns:
        Brief summary string
    """
    if command_type == "exec_shell":
        cmd = payload.get("cmd", "")
        return cmd[:80] + "..." if len(cmd) > 80 else cmd

    elif command_type == "pkg_install":
        name = payload.get("name", "")
        manager = payload.get("manager", "auto")
        return f"{name} (via {manager})"

    elif command_type == "file_write":
        path = payload.get("path", "")
        return f"Write to {path}"

    elif command_type == "service_restart":
        service = payload.get("service_name", "")
        return f"Restart {service}"

    elif command_type == "reboot":
        delay = payload.get("delay_s", 30)
        return f"Reboot in {delay}s"

    elif command_type == "agent_upgrade":
        version = payload.get("version", "")
        return f"Upgrade to v{version}"

    else:
        # Generic: show keys only
        keys = ", ".join(payload.keys())
        return f"({keys})"
