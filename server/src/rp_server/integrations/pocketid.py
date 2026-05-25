"""PocketID OIDC integration client.

F5 implementation. Provides OIDC userinfo fetching and optional admin API
for user sync operations.
"""

import logging
from typing import Any

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class PocketIDClient:
    """OIDC client for PocketID identity provider."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: SecretStr | None = None,
        admin_token: SecretStr | None = None,
    ):
        """Initialize PocketID client.

        Args:
            base_url: PocketID base URL (e.g. https://id.monxas.casa)
            client_id: OIDC client ID
            client_secret: OIDC client secret (optional, for token exchange)
            admin_token: Admin API token (optional, for user sync)
        """
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.admin_token = admin_token

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        """Fetch OIDC userinfo from PocketID.

        Args:
            access_token: Bearer token from Caddy forward_auth

        Returns:
            dict with OIDC standard claims (sub, email, name, picture, etc.)

        Raises:
            httpx.HTTPStatusError: On non-2xx response
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/oidc/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            logger.debug(
                "PocketID userinfo fetched",
                extra={"sub": data.get("sub"), "email": data.get("email")},
            )

            return data

    async def list_users(self) -> list[dict[str, Any]]:
        """List all users from PocketID admin API.

        Requires admin_token to be configured.

        Returns:
            List of user dicts with fields: sub, email, name, picture, groups

        Raises:
            ValueError: If admin_token not configured
            httpx.HTTPStatusError: On non-2xx response
        """
        if not self.admin_token:
            raise ValueError("admin_token not configured for PocketID client")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/admin/users",
                headers={"Authorization": f"Bearer {self.admin_token.get_secret_value()}"},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            logger.info(
                "PocketID users list fetched",
                extra={"user_count": len(data)},
            )

            return data


def get_pocketid_client() -> PocketIDClient:
    """Get configured PocketID client from settings.

    Returns cached client instance to reuse HTTP connections.
    """
    from rp_server.config import settings

    return PocketIDClient(
        base_url=str(settings.pocketid_base_url),
        client_id=settings.pocketid_client_id,
        client_secret=settings.pocketid_client_secret,
        admin_token=settings.pocketid_admin_token,
    )
