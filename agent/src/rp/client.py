"""HTTP client for communicating with Remote-Pulse server."""

import asyncio
from typing import Any, Optional

import httpx
import structlog

from rp.compat import APICompatHandler
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
        self._compat_handler = APICompatHandler(config.server_url)

    async def __aenter__(self):
        """Async context manager entry."""
        # Prepare default headers with version info
        default_headers = {"User-Agent": "remote-pulse-agent/0.1.0"}
        default_headers = self._compat_handler.add_version_headers(default_headers)

        self._client = httpx.AsyncClient(
            base_url=self.config.server_url,
            timeout=self.timeout,
            headers=default_headers,
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

                # Handle compatibility response headers
                self._compat_handler.handle_compat_response(response)

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
        # Server's HeartbeatRequest schema is flat (cpu_pct / mem_pct / ...)
        # at the top level — not nested under "metrics". Also convert
        # agent_ts from float seconds to ISO so Pydantic's datetime parser
        # accepts it.
        from datetime import datetime, timezone

        flat_metrics = dict(metrics)
        if isinstance(flat_metrics.get("agent_ts"), (int, float)):
            flat_metrics["agent_ts"] = datetime.fromtimestamp(
                flat_metrics["agent_ts"], tz=timezone.utc
            ).isoformat()

        payload = {"host_id": self.config.host_id, **flat_metrics}

        logger.debug("sending heartbeat", host_id=self.config.host_id)
        return await self._request("POST", "/v1/heartbeat", json=payload)

    async def update_capabilities(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        """
        Report updated host capabilities to the server.

        POSTs to ``/v1/hosts/{host_id}/capabilities`` so the dashboard and
        ``rp screen`` resolver pick up the new state immediately (without
        waiting for the next heartbeat).

        Returns:
            Server response payload (best-effort; warns if endpoint missing).
        """
        path = f"/v1/hosts/{self.config.host_id}/capabilities"
        payload = {
            "host_id": self.config.host_id,
            "capabilities": capabilities,
        }
        logger.info(
            "updating_capabilities",
            host_id=self.config.host_id,
            keys=sorted(capabilities.keys()),
        )
        try:
            return await self._request("POST", path, json=payload, retry_count=2)
        except httpx.HTTPError as e:
            logger.warning("update_capabilities_failed", error=str(e), path=path)
            return {
                "status": "warning",
                "message": "Capabilities endpoint not available; "
                "will resync on next heartbeat.",
            }

    async def poll_commands(self) -> list[dict[str, Any]]:
        """Pull approved-but-not-yet-executed commands for this host.

        Phase 2.5: hits ``GET /v1/agent/commands/pending`` (see the
        ``agent_commands`` router). Returns the raw command dicts as
        emitted by the server; the daemon converts them to
        :class:`rp.commands.runner.RemoteCommand` before dispatch.
        """
        path = f"/v1/agent/commands/pending?host_id={self.config.host_id}"
        # retry_count=1 so a slow server doesn't stack 3x retries on every
        # 5s poll. The daemon's own back-off layer handles repeated misses.
        resp = await self._request("GET", path, retry_count=1)
        commands = resp.get("commands", [])
        if not isinstance(commands, list):
            logger.warning(
                "poll_commands: server returned non-list commands payload",
                got=type(commands).__name__,
            )
            return []
        return commands

    async def post_command_result(
        self,
        command_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Report execution outcome to the server.

        ``result`` keys: ``exit_code`` (int|None), ``stdout`` (str),
        ``stderr`` (str), ``duration_ms`` (int), ``agent_ts`` (ISO str),
        ``rejected_reason`` (str|None).
        """
        path = (
            f"/v1/agent/commands/{command_id}/result?host_id={self.config.host_id}"
        )
        return await self._request("POST", path, json=result, retry_count=3)

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

    async def version_handshake(
        self,
        agent_version: str,
        api_compat_min: str,
        api_compat_max: str,
    ) -> dict[str, Any]:
        """
        Send version handshake to server after upgrade.

        Args:
            agent_version: New agent version
            api_compat_min: Minimum compatible API version
            api_compat_max: Maximum compatible API version

        Returns:
            Server response
        """
        payload = {
            "host_id": self.config.host_id,
            "agent_version": agent_version,
            "api_compat_min": api_compat_min,
            "api_compat_max": api_compat_max,
        }

        logger.info(
            "sending version handshake",
            host_id=self.config.host_id,
            agent_version=agent_version,
        )
        return await self._request("POST", "/v1/agent/version-handshake", json=payload)

    async def report_rollback(
        self,
        from_version: str,
        to_version: str,
        reason: str,
    ) -> dict[str, Any]:
        """
        Report rollback to server.

        Args:
            from_version: Version rolled back from
            to_version: Version rolled back to
            reason: Rollback reason

        Returns:
            Server response
        """
        payload = {
            "host_id": self.config.host_id,
            "from_version": from_version,
            "to_version": to_version,
            "reason": reason,
        }

        logger.info(
            "reporting rollback",
            host_id=self.config.host_id,
            from_version=from_version,
            to_version=to_version,
            reason=reason,
        )
        return await self._request("POST", "/v1/agent/rollback", json=payload)

    async def send_heartbeat(self) -> dict[str, Any]:
        """
        Send minimal heartbeat for self-check.

        Returns:
            Server response
        """
        return await self._request(
            "POST",
            "/v1/heartbeat",
            json={"host_id": self.config.host_id},
        )

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
