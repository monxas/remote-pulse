"""API compatibility middleware for version negotiation.

Enforces N-2 version skew tolerance and version handshake protocol.
See ADR-0008 Appendix G.
"""

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from rp_server.compat import (
    API_FEATURES,
    SERVER_API_VERSION,
    SERVER_MIN_AGENT_VERSION,
    get_deprecation_reason,
    is_version_compatible,
)

logger = structlog.get_logger()


class APICompatMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce API compatibility and version negotiation.

    Request headers expected (from agent):
        Sec-RP-Agent-Version: 0.5.2
        Sec-RP-Min-Server: 0.5.0
        Sec-RP-Features: heartbeat,signed_commands

    Response headers set:
        Sec-RP-Server-Version: 1.0.0
        Sec-RP-Min-Agent: 0.1.0
        Sec-RP-Features: enroll,heartbeat,metrics_sparkline,...
        Sec-RP-Deprecated: false  # or "true" with reason

    Behavior:
        - Agent version < SERVER_MIN_AGENT_VERSION -> 426 Upgrade Required
        - Agent version in deprecated list -> still serve + warn header
        - Server version < agent's Sec-RP-Min-Server -> 426 (server too old)
        - Missing headers (e.g. health check) -> skip enforcement
    """

    async def dispatch(self, request: Request, call_next):
        """Process request with version compatibility checks."""
        # Always add server version headers to response
        response = None

        # Skip version checks for specific endpoints (health, root, docs, /metrics)
        skip_paths = ["/health", "/", "/docs", "/openapi.json", "/metrics"]
        if any(request.url.path.startswith(p) for p in skip_paths):
            response = await call_next(request)
            self._add_server_headers(response)
            return response

        # Extract agent version from headers
        agent_version = request.headers.get("Sec-RP-Agent-Version")
        agent_min_server = request.headers.get("Sec-RP-Min-Server")
        # agent_features = request.headers.get("Sec-RP-Features", "").split(",")  # TODO: Use for feature negotiation

        # If headers missing, allow request (backward compat with bootstrap/old agents)
        if not agent_version:
            logger.debug(
                "Request without agent version headers",
                path=request.url.path,
                user_agent=request.headers.get("User-Agent"),
            )
            response = await call_next(request)
            self._add_server_headers(response)
            return response

        # Log version handshake
        logger.debug(
            "Version handshake",
            agent_version=agent_version,
            agent_min_server=agent_min_server,
            path=request.url.path,
        )

        # Check if server is too old for this agent
        if agent_min_server and not is_version_compatible(SERVER_API_VERSION, agent_min_server):
            logger.warning(
                "Server version too old for agent",
                server_version=SERVER_API_VERSION,
                agent_min_server=agent_min_server,
                agent_version=agent_version,
            )
            return Response(
                content=(
                    f'{{"error": "server_version_too_old", '
                    f'"detail": "Server {SERVER_API_VERSION} < agent minimum {agent_min_server}. '
                    f'Server upgrade required."}}'
                ),
                status_code=426,
                media_type="application/json",
            )

        # Check if agent is too old for this server
        if not is_version_compatible(agent_version, SERVER_MIN_AGENT_VERSION):
            logger.warning(
                "Agent version too old",
                agent_version=agent_version,
                min_agent_version=SERVER_MIN_AGENT_VERSION,
            )
            return Response(
                content=(
                    f'{{"error": "agent_version_too_old", '
                    f'"detail": "Agent {agent_version} < server minimum {SERVER_MIN_AGENT_VERSION}. '
                    f'Agent upgrade required.", '
                    f'"required": ">={SERVER_MIN_AGENT_VERSION}"}}'
                ),
                status_code=426,
                media_type="application/json",
            )

        # Check for deprecation (allow but warn)
        deprecation_reason = get_deprecation_reason(agent_version)

        # Process request
        response = await call_next(request)

        # Add server version headers and deprecation warning
        self._add_server_headers(response, deprecation_reason)

        if deprecation_reason:
            logger.warning(
                "Deprecated agent version detected",
                agent_version=agent_version,
                reason=deprecation_reason,
            )

        return response

    def _add_server_headers(
        self, response: Response, deprecation_reason: str | None = None
    ) -> None:
        """Add server version and compatibility headers to response.

        Args:
            response: Response object to modify
            deprecation_reason: Optional deprecation message
        """
        response.headers["Sec-RP-Server-Version"] = SERVER_API_VERSION
        response.headers["Sec-RP-Min-Agent"] = SERVER_MIN_AGENT_VERSION
        response.headers["Sec-RP-Features"] = ",".join(API_FEATURES)

        if deprecation_reason:
            response.headers["Sec-RP-Deprecated"] = "true"
            response.headers["Sec-RP-Deprecated-Reason"] = deprecation_reason
        else:
            response.headers["Sec-RP-Deprecated"] = "false"
