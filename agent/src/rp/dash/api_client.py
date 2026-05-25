"""Async API client for dashboard data fetching."""

from datetime import datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class AsyncAPIClient:
    """Async HTTP client for Remote-Pulse server API."""

    def __init__(self, server_url: str, timeout: float = 5.0):
        """
        Initialize async API client.

        Args:
            server_url: Server base URL
            timeout: Request timeout in seconds
        """
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Initialize HTTP client connection."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.server_url,
                timeout=self.timeout,
                headers={"User-Agent": "remote-pulse-dashboard/0.1.0"},
            )

    async def close(self) -> None:
        """Close HTTP client connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_hosts(self) -> list[dict[str, Any]]:
        """
        Fetch list of all hosts.

        Returns:
            List of host summary objects

        Raises:
            httpx.HTTPError: On request failure
        """
        if not self._client:
            raise RuntimeError("Client not connected, call connect() first")

        logger.debug("fetching host list")
        response = await self._client.get("/v1/hosts")
        response.raise_for_status()
        return response.json()

    async def get_host_detail(self, host_id: str) -> dict[str, Any]:
        """
        Fetch detailed host information with recent heartbeats.

        Args:
            host_id: Host UUID

        Returns:
            Host detail object with recent_heartbeats list

        Raises:
            httpx.HTTPError: On request failure
        """
        if not self._client:
            raise RuntimeError("Client not connected, call connect() first")

        logger.debug("fetching host detail", host_id=host_id)
        response = await self._client.get(f"/v1/hosts/{host_id}")
        response.raise_for_status()
        return response.json()

    async def get_sparkline(
        self,
        host_id: str,
        metrics: list[str],
        window: str = "5m",
    ) -> dict[str, list[tuple[datetime, float]]]:
        """
        Fetch sparkline data for host metrics.

        F3 MVP: Try dedicated /v1/metrics/{host_id}/sparkline endpoint.
        If 404 (endpoint not built yet), fallback to /v1/hosts/{id}.recent_heartbeats.

        Args:
            host_id: Host UUID
            metrics: List of metric names (cpu_pct, mem_pct, load_1m)
            window: Time window (5m, 15m, 1h, 6h, 24h)

        Returns:
            Dict mapping metric_name -> list[(timestamp, value)]

        Raises:
            httpx.HTTPError: On fatal request failure
        """
        if not self._client:
            raise RuntimeError("Client not connected, call connect() first")

        # Try dedicated sparkline endpoint first (F3 target)
        try:
            logger.debug(
                "fetching sparkline", host_id=host_id, metrics=metrics, window=window
            )

            params = {"window": window}
            for metric in metrics:
                params["series"] = metric  # httpx will create multiple series params

            response = await self._client.get(
                f"/v1/metrics/{host_id}/sparkline",
                params=params,
            )
            response.raise_for_status()

            data = response.json()

            # Parse SparklineResponse format
            result = {}
            for series in data.get("series", []):
                metric = series["metric"]
                # Convert ISO strings to datetime objects
                points = [
                    (datetime.fromisoformat(ts.replace("Z", "+00:00")), val)
                    for ts, val in series["points"]
                ]
                result[metric] = points

            logger.debug("sparkline fetched from dedicated endpoint", host_id=host_id)
            return result

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Endpoint not built yet, fallback to recent_heartbeats
                logger.info(
                    "sparkline endpoint 404, falling back to recent_heartbeats",
                    host_id=host_id,
                )
                return await self._get_sparkline_fallback(host_id, metrics)
            raise

    async def _get_sparkline_fallback(
        self,
        host_id: str,
        metrics: list[str],
    ) -> dict[str, list[tuple[datetime, float]]]:
        """
        Fallback: construct sparkline from recent_heartbeats in host detail.

        Args:
            host_id: Host UUID
            metrics: Metric names to extract

        Returns:
            Dict mapping metric_name -> list[(timestamp, value)]
        """
        logger.debug("using fallback sparkline from recent_heartbeats", host_id=host_id)

        detail = await self.get_host_detail(host_id)
        heartbeats = detail.get("recent_heartbeats", [])

        result = {metric: [] for metric in metrics}

        for hb in reversed(heartbeats):  # recent_heartbeats is desc, reverse for asc
            ts_str = hb.get("ts")
            if not ts_str:
                continue

            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

            for metric in metrics:
                value = hb.get(metric)
                if value is not None:
                    result[metric].append((ts, value))

        logger.debug(
            "fallback sparkline constructed",
            host_id=host_id,
            points_per_metric={k: len(v) for k, v in result.items()},
        )

        return result
