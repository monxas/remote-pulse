"""Tailscale API client for ephemeral auth-key generation."""

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TailscaleAuthKeyCapabilities(BaseModel):
    """Capabilities for Tailscale auth key."""

    devices: dict[str, Any]


class TailscaleAuthKeyResponse(BaseModel):
    """Response from Tailscale auth key creation."""

    id: str
    key: str
    created: str
    expires: str
    revoked: bool
    capabilities: TailscaleAuthKeyCapabilities
    description: str | None = None


class TailscaleAPIError(Exception):
    """Base exception for Tailscale API errors."""

    pass


class TailscaleAuthenticationError(TailscaleAPIError):
    """Raised when API key is invalid (401)."""

    pass


class TailscalePermissionError(TailscaleAPIError):
    """Raised when API key lacks required scope (403)."""

    pass


class TailscaleValidationError(TailscaleAPIError):
    """Raised when request payload is invalid (422)."""

    pass


class TailscaleAPIClient:
    """Async wrapper for Tailscale API operations."""

    def __init__(
        self,
        api_key: str,
        tailnet: str = "-",
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        """
        Initialize Tailscale API client.

        Args:
            api_key: Tailscale API key (tskey-api-xxxx)
            tailnet: Tailnet identifier ("-" = default tailnet of API key owner)
            timeout: Request timeout in seconds
            max_retries: Number of retry attempts for transient errors
        """
        self.api_key = api_key
        self.tailnet = tailnet
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://api.tailscale.com/api/v2"

    async def create_authkey(
        self,
        *,
        ephemeral: bool = True,
        reusable: bool = False,
        preauthorized: bool = True,
        expiry_seconds: int = 86400,
        tags: list[str],
        description: str | None = None,
    ) -> TailscaleAuthKeyResponse:
        """
        Create a Tailscale auth key.

        Args:
            ephemeral: Device disappears from admin console when it goes offline
            reusable: Key can be used multiple times (default False)
            preauthorized: Device is pre-approved and doesn't require admin approval
            expiry_seconds: Key expiration time (default 24h)
            tags: ACL tags to assign to devices (e.g., ["tag:rp-agent-prod"])
            description: Human-readable description for audit trail

        Returns:
            TailscaleAuthKeyResponse with auth key string

        Raises:
            TailscaleAuthenticationError: Invalid API key
            TailscalePermissionError: Insufficient permissions
            TailscaleValidationError: Invalid request payload
            TailscaleAPIError: Other API errors
        """
        url = f"{self.base_url}/tailnet/{self.tailnet}/keys"

        payload = {
            "capabilities": {
                "devices": {
                    "create": {
                        "reusable": reusable,
                        "ephemeral": ephemeral,
                        "preauthorized": preauthorized,
                        "tags": tags,
                    }
                }
            },
            "expirySeconds": expiry_seconds,
        }

        if description:
            payload["description"] = description

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        auth=(
                            self.api_key,
                            "",
                        ),  # HTTP Basic auth (username=api_key, password=empty)
                    )

                    # Handle error responses
                    if response.status_code == 401:
                        logger.error(
                            "Tailscale API authentication failed",
                            extra={"status": 401, "response": response.text},
                        )
                        raise TailscaleAuthenticationError(
                            "Invalid Tailscale API key (401 Unauthorized)"
                        )

                    if response.status_code == 403:
                        logger.error(
                            "Tailscale API permission denied",
                            extra={"status": 403, "response": response.text},
                        )
                        raise TailscalePermissionError(
                            "API key lacks required scope (403 Forbidden). "
                            "Ensure key has 'Devices: Write' permission."
                        )

                    if response.status_code == 422:
                        logger.error(
                            "Tailscale API validation error",
                            extra={"status": 422, "response": response.text, "payload": payload},
                        )
                        raise TailscaleValidationError(
                            f"Invalid request payload (422 Unprocessable): {response.text}"
                        )

                    if response.status_code >= 500:
                        # Retry transient server errors
                        if attempt < self.max_retries - 1:
                            backoff = 2**attempt
                            logger.warning(
                                "Tailscale API server error, retrying",
                                extra={
                                    "status": response.status_code,
                                    "attempt": attempt + 1,
                                    "backoff_s": backoff,
                                },
                            )
                            await asyncio.sleep(backoff)
                            continue
                        raise TailscaleAPIError(
                            f"Tailscale API server error ({response.status_code}): {response.text}"
                        )

                    response.raise_for_status()

                    data = response.json()
                    logger.info(
                        "Tailscale auth key created",
                        extra={
                            "key_id": data.get("id"),
                            "tags": tags,
                            "ephemeral": ephemeral,
                            "description": description,
                        },
                    )

                    return TailscaleAuthKeyResponse(**data)

            except httpx.TimeoutException as e:
                if attempt < self.max_retries - 1:
                    backoff = 2**attempt
                    logger.warning(
                        "Tailscale API timeout, retrying",
                        extra={"attempt": attempt + 1, "backoff_s": backoff},
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error("Tailscale API timeout after retries", exc_info=e)
                raise TailscaleAPIError(f"Tailscale API timeout after {self.max_retries} retries")

            except httpx.RequestError as e:
                if attempt < self.max_retries - 1:
                    backoff = 2**attempt
                    logger.warning(
                        "Tailscale API request error, retrying",
                        extra={"attempt": attempt + 1, "backoff_s": backoff, "error": str(e)},
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error("Tailscale API request failed after retries", exc_info=e)
                raise TailscaleAPIError(f"Tailscale API request error: {e}")

        # Should never reach here due to raise in loop, but satisfy type checker
        raise TailscaleAPIError("Unexpected retry loop exit")
