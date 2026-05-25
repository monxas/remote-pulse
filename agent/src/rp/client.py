"""HTTP client for communicating with Remote-Pulse server."""

import asyncio
from typing import Any, Optional

import httpx
import structlog

from rp.config import AgentConfig

logger = structlog.get_logger()


class RPClient:
    """Client for Remote-Pulse server API."""

    def __init__(self, config: AgentConfig, timeout: float = 10.0):
        """
        Initialize client.

        Args:
            config: Agent configuration
            timeout: Request timeout in seconds
        """
        self.config = config
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            base_url=self.config.server_url,
            timeout=self.timeout,
            headers={"User-Agent": "remote-pulse-agent/0.1.0"},
        )
        return self

    async def __aexit__(self, *args):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        retry_count: int = 3,
    ) -> dict[str, Any]:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method
            path: Request path
            json: JSON body
            retry_count: Number of retries

        Returns:
            Response JSON

        Raises:
            httpx.HTTPError: On failure after retries
        """
        if not self._client:
            raise RuntimeError("Client not initialized, use async with")

        last_error = None
        backoff = 1.0

        for attempt in range(retry_count):
            try:
                logger.debug(
                    "http request",
                    method=method,
                    path=path,
                    attempt=attempt + 1,
                )

                response = await self._client.request(method, path, json=json)
                response.raise_for_status()

                return response.json()

            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "http request failed",
                    method=method,
                    path=path,
                    attempt=attempt + 1,
                    error=str(e),
                )

                if attempt < retry_count - 1:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)  # Exponential backoff, max 60s

        # All retries exhausted
        logger.error("http request failed after retries", error=str(last_error))
        raise last_error

    async def enroll(
        self,
        token: str,
        hostname: str,
        host_fingerprint: str,
        group: Optional[str] = None,
        platform_info: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Enroll host with server.

        Args:
            token: Enrollment JWT token
            hostname: Host name
            host_fingerprint: Unique host fingerprint
            group: Optional group name
            platform_info: Optional platform details

        Returns:
            Enrollment response with host_id and agent_config
        """
        payload = {
            "token": token,
            "hostname": hostname,
            "host_fingerprint": host_fingerprint,
        }

        if group:
            payload["group"] = group

        if platform_info:
            payload["platform"] = platform_info

        logger.info("enrolling with server", hostname=hostname)
        return await self._request("POST", "/v1/enroll", json=payload)

    async def heartbeat(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """
        Send heartbeat with metrics.

        Args:
            metrics: Metrics dictionary

        Returns:
            Server response
        """
        payload = {
            "host_id": self.config.host_id,
            "metrics": metrics,
        }

        logger.debug("sending heartbeat", host_id=self.config.host_id)
        return await self._request("POST", "/v1/heartbeat", json=payload)

    async def deregister(self) -> dict[str, Any]:
        """
        Deregister host from server.

        Returns:
            Server response
        """
        logger.info("deregistering host", host_id=self.config.host_id)

        try:
            return await self._request(
                "DELETE",
                f"/v1/hosts/{self.config.host_id}",
                retry_count=1,  # Don't retry delete
            )
        except httpx.HTTPError as e:
            # F1: Server endpoint may not exist yet, fail gracefully
            logger.warning("deregister failed (endpoint may not exist)", error=str(e))
            return {"status": "warning", "message": "Server endpoint not available"}

    async def get(self, path: str, **kwargs) -> httpx.Response:
        """
        HTTP GET request.

        Args:
            path: Request path
            **kwargs: Additional httpx.request arguments

        Returns:
            httpx.Response object
        """
        if not self._client:
            raise RuntimeError("Client not initialized, use async with")

        return await self._client.get(path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        """
        HTTP POST request.

        Args:
            path: Request path
            **kwargs: Additional httpx.request arguments (json, data, etc.)

        Returns:
            httpx.Response object
        """
        if not self._client:
            raise RuntimeError("Client not initialized, use async with")

        return await self._client.post(path, **kwargs)


def create_sync_client(server_url: str, timeout: float = 10.0) -> httpx.Client:
    """
    Create synchronous HTTP client for install command.

    Args:
        server_url: Server base URL
        timeout: Request timeout

    Returns:
        Synchronous httpx client
    """
    return httpx.Client(
        base_url=server_url,
        timeout=timeout,
        headers={"User-Agent": "remote-pulse-agent/0.1.0"},
    )
