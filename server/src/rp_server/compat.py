"""API compatibility policy and version negotiation.

See ADR-0008 Appendix G for policy details.
"""

from typing import Literal

# Server API version - bump on breaking changes
SERVER_API_VERSION = "1.0.0"

# Oldest agent version we still support (N-2 policy)
SERVER_MIN_AGENT_VERSION = "0.1.0"

# Agent versions that still work but trigger deprecation warnings
SERVER_DEPRECATED_AGENT_VERSIONS = ["0.0.x"]

# Feature flags announced to agents via /v1/server/info
API_FEATURES = [
    "enroll",
    "heartbeat",
    "metrics_sparkline",
    "ssh_keys_lifecycle",
    "signed_commands",
    "telegram_approval",
    "prometheus_metrics",
    "tailscale_identity",
    "multi_user_oidc",  # F5
    "websocket_multichannel",  # F4-future
    "agent_canary_upgrade",  # F8-4
]


def semver_compare(a: str, b: str) -> Literal[-1, 0, 1]:
    """Compare two semantic versions (X.Y.Z format).

    Args:
        a: First version string
        b: Second version string

    Returns:
        -1 if a < b
         0 if a == b
         1 if a > b

    Raises:
        ValueError: If version strings are not valid semver
    """
    try:
        a_parts = [int(x) for x in a.split(".")]
        b_parts = [int(x) for x in b.split(".")]

        if len(a_parts) != 3 or len(b_parts) != 3:
            raise ValueError("Version must be X.Y.Z format")

        for a_num, b_num in zip(a_parts, b_parts):
            if a_num < b_num:
                return -1
            elif a_num > b_num:
                return 1

        return 0

    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid semver format: {a!r} or {b!r}") from e


def is_version_compatible(agent_version: str, min_version: str) -> bool:
    """Check if agent version meets minimum requirement.

    Args:
        agent_version: Agent's version string
        min_version: Minimum required version

    Returns:
        True if agent_version >= min_version
    """
    return semver_compare(agent_version, min_version) >= 0


def is_version_deprecated(agent_version: str) -> bool:
    """Check if agent version is in deprecation list.

    Supports wildcard patterns like "0.0.x".

    Args:
        agent_version: Agent's version string

    Returns:
        True if version matches any deprecation pattern
    """
    for pattern in SERVER_DEPRECATED_AGENT_VERSIONS:
        if pattern.endswith(".x"):
            # Wildcard match - check major.minor prefix
            prefix = pattern[:-2]  # Remove '.x'
            if agent_version.startswith(prefix):
                return True
        elif agent_version == pattern:
            return True

    return False


def get_deprecation_reason(agent_version: str) -> str | None:
    """Get deprecation message for a deprecated version.

    Args:
        agent_version: Agent's version string

    Returns:
        Deprecation message if deprecated, None otherwise
    """
    if not is_version_deprecated(agent_version):
        return None

    return (
        f"Agent version {agent_version} is deprecated and will be unsupported "
        f"in future releases. Please upgrade to >={SERVER_MIN_AGENT_VERSION}."
    )
