"""Agent-side API compatibility handler.

Manages agent-server version handshake and compatibility checks.
See ADR-0008 Appendix G for version negotiation policy.
"""

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from rp import __version__

logger = structlog.get_logger()


# Agent version and compatibility range
AGENT_VERSION = __version__
AGENT_MIN_SERVER_VERSION = "0.1.0"  # Oldest server we can talk to

# Features this agent supports
AGENT_FEATURES = [
    "enroll",
    "heartbeat",
    "metrics_sparkline",
    "ssh_keys_lifecycle",
    "signed_commands",
]


@dataclass
class ServerInfo:
    """Server capability information."""

    server_version: str
    api_version: str
    min_agent_version: str
    deprecated_agent_versions: list[str]
    features: list[str]
    tailscale_ssh_supported: bool
    rustdesk_direct_ip_supported: bool
    sunshine_supported: bool
    max_metrics_window: str
    metrics_retention_policy: dict[str, Any]


class IncompatibleVersionError(Exception):
    """Raised when agent-server version compatibility check fails."""

    pass


class APICompatHandler:
    """Manages agent-server version handshake and compatibility."""

    def __init__(self, server_url: str):
        """Initialize compat handler.

        Args:
            server_url: Base URL of Remote-Pulse server
        """
        self.server_url = server_url
        self.server_info: ServerInfo | None = None

    async def check_handshake(self) -> ServerInfo:
        """Perform version handshake with server.

        On startup or before first request:
        1. GET /v1/server/info
        2. Compare server.min_agent_version vs AGENT_VERSION
        3. Compare AGENT_MIN_SERVER vs server.server_version
        4. Log warning if features missing
        5. Raise IncompatibleVersionError if hard mismatch

        Returns:
            ServerInfo with capabilities

        Raises:
            IncompatibleVersionError: If version skew is too large
            httpx.HTTPError: If server unreachable
        """
        logger.info(
            "Checking version compatibility with server",
            agent_version=AGENT_VERSION,
            server_url=self.server_url,
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"{self.server_url}/v1/server/info")
                response.raise_for_status()
                data = response.json()

            except httpx.HTTPError as e:
                logger.error("Failed to fetch server info", error=str(e))
                raise

        # Parse server info
        server_info = ServerInfo(
            server_version=data["server_version"],
            api_version=data["api_version"],
            min_agent_version=data["min_agent_version"],
            deprecated_agent_versions=data.get("deprecated_agent_versions", []),
            features=data.get("features", []),
            tailscale_ssh_supported=data.get("tailscale_ssh_supported", False),
            rustdesk_direct_ip_supported=data.get(
                "rustdesk_direct_ip_supported", False
            ),
            sunshine_supported=data.get("sunshine_supported", False),
            max_metrics_window=data.get("max_metrics_window", "1y"),
            metrics_retention_policy=data.get("metrics_retention_policy", {}),
        )

        # Check if server is too old for this agent
        if not self._is_version_compatible(
            server_info.server_version, AGENT_MIN_SERVER_VERSION
        ):
            msg = (
                f"Server version {server_info.server_version} is older than "
                f"agent minimum {AGENT_MIN_SERVER_VERSION}. Server upgrade required."
            )
            logger.error("Server too old", error=msg)
            raise IncompatibleVersionError(msg)

        # Check if agent is too old for server
        if not self._is_version_compatible(
            AGENT_VERSION, server_info.min_agent_version
        ):
            msg = (
                f"Agent version {AGENT_VERSION} is older than "
                f"server minimum {server_info.min_agent_version}. Agent upgrade required."
            )
            logger.error("Agent too old", error=msg)
            raise IncompatibleVersionError(msg)

        # Check for deprecation (warn but allow)
        if self._is_version_deprecated(
            AGENT_VERSION, server_info.deprecated_agent_versions
        ):
            logger.warning(
                "Agent version is deprecated",
                agent_version=AGENT_VERSION,
                deprecated_list=server_info.deprecated_agent_versions,
            )

        # Log missing features (agent supports but server doesn't)
        missing_features = set(AGENT_FEATURES) - set(server_info.features)
        if missing_features:
            logger.warning(
                "Server missing features agent expects",
                missing=list(missing_features),
            )

        # Log extra features (server has but agent doesn't need yet)
        extra_features = set(server_info.features) - set(AGENT_FEATURES)
        if extra_features:
            logger.debug(
                "Server has features agent doesn't use yet",
                extra=list(extra_features),
            )

        logger.info(
            "Version handshake successful",
            server_version=server_info.server_version,
            agent_version=AGENT_VERSION,
            compatible=True,
        )

        self.server_info = server_info
        return server_info

    def add_version_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Add agent version headers to request.

        Args:
            headers: Existing headers dict

        Returns:
            Updated headers dict with version info
        """
        headers["Sec-RP-Agent-Version"] = AGENT_VERSION
        headers["Sec-RP-Min-Server"] = AGENT_MIN_SERVER_VERSION
        headers["Sec-RP-Features"] = ",".join(AGENT_FEATURES)

        return headers

    def handle_compat_response(self, response: httpx.Response) -> None:
        """Process server compatibility response headers.

        Logs warning if agent is deprecated.

        Args:
            response: HTTP response from server
        """
        deprecated = response.headers.get("Sec-RP-Deprecated", "false")
        if deprecated.lower() == "true":
            reason = response.headers.get(
                "Sec-RP-Deprecated-Reason", "Agent version deprecated"
            )
            logger.warning("Server flagged agent as deprecated", reason=reason)

        server_version = response.headers.get("Sec-RP-Server-Version")
        if server_version:
            logger.debug(
                "Server version from response",
                server_version=server_version,
                agent_version=AGENT_VERSION,
            )

    @staticmethod
    def _is_version_compatible(version: str, min_version: str) -> bool:
        """Check if version >= min_version (semver).

        Args:
            version: Version to check
            min_version: Minimum required version

        Returns:
            True if version >= min_version
        """
        try:
            v_parts = [int(x) for x in version.split(".")]
            m_parts = [int(x) for x in min_version.split(".")]

            if len(v_parts) != 3 or len(m_parts) != 3:
                return False

            for v_num, m_num in zip(v_parts, m_parts):
                if v_num < m_num:
                    return False
                elif v_num > m_num:
                    return True

            return True  # Equal

        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _is_version_deprecated(version: str, deprecated_list: list[str]) -> bool:
        """Check if version matches any deprecation pattern.

        Supports wildcard patterns like "0.0.x".

        Args:
            version: Version to check
            deprecated_list: List of deprecated version patterns

        Returns:
            True if version matches any pattern
        """
        for pattern in deprecated_list:
            if pattern.endswith(".x"):
                # Wildcard match - check major.minor prefix
                prefix = pattern[:-2]
                if version.startswith(prefix):
                    return True
            elif version == pattern:
                return True

        return False
