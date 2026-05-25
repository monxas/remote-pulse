"""Pydantic request/response schemas."""

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnrollRequest(BaseModel):
    """Agent enrollment request payload."""

    token: str = Field(description="JWT enrollment token")
    hostname: str = Field(min_length=1, max_length=255)
    group: str = Field(default="default", max_length=100)
    host_fingerprint: str = Field(
        description="Host hardware fingerprint (e.g. machine-id or MAC)",
        min_length=1,
        max_length=255,
    )
    os: str = Field(examples=["linux", "macos", "windows"])
    arch: str = Field(examples=["x86_64", "arm64"])
    distro: str | None = Field(default=None, examples=["debian-12", "macos-14", "win-11"])
    agent_version: str


class AgentConfig(BaseModel):
    """Agent configuration returned after enrollment."""

    server_url: str
    heartbeat_interval_s: int
    tailscale_authkey: str | None = Field(
        default=None,
        description="Ephemeral Tailscale auth-key for joining tailnet (F2)",
    )
    server_pubkey: str | None = Field(
        default=None,
        description="Server's Ed25519 public key PEM for command verification (F4)",
    )
    server_pubkey_fingerprint: str | None = Field(
        default=None,
        description="SHA256 fingerprint of server pubkey for trust pinning (F4)",
    )


class EnrollResponse(BaseModel):
    """Enrollment response with host ID and config."""

    host_id: uuid.UUID
    agent_config: AgentConfig


class HeartbeatRequest(BaseModel):
    """Agent heartbeat payload."""

    host_id: uuid.UUID
    cpu_pct: float | None = Field(default=None, ge=0, le=100)
    mem_pct: float | None = Field(default=None, ge=0, le=100)
    load_1m: float | None = Field(default=None, ge=0)
    uptime_s: int | None = Field(default=None, ge=0)
    agent_version: str
    agent_ts: datetime | None = Field(
        default=None,
        description="Agent timestamp for clock skew detection",
    )


class HeartbeatResponse(BaseModel):
    """Heartbeat acknowledgment."""

    status: str = "ok"
    server_ts: datetime


class HeartbeatData(BaseModel):
    """Heartbeat data for responses."""

    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    cpu_pct: float | None
    mem_pct: float | None
    load_1m: float | None
    uptime_s: int | None
    agent_version: str | None


class HostListItem(BaseModel):
    """Host summary for list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    os: str
    arch: str
    agent_version: str
    group_name: str | None
    enrolled_at: datetime
    last_seen_at: datetime | None


class HostDetail(BaseModel):
    """Detailed host information."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    fqdn: str | None
    tailscale_node_id: str | None
    os: str
    arch: str
    distro: str | None
    agent_version: str
    enrolled_at: datetime
    last_seen_at: datetime | None
    group_name: str | None
    capabilities: dict
    metadata: dict
    recent_heartbeats: list[HeartbeatData] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


class SparklineSeries(BaseModel):
    """Time series data for a single metric."""

    metric: str = Field(description="Metric name (e.g. 'cpu_pct', 'mem_pct')")
    points: list[tuple[datetime, float]] = Field(
        description="List of (timestamp, value) tuples sorted ascending by timestamp"
    )


class SparklineResponse(BaseModel):
    """Sparkline data response for multiple metrics over a time window."""

    host_id: uuid.UUID
    window: str = Field(description="Time window requested (e.g. '5m', '1h', '24h')")
    series: list[SparklineSeries]
    bucket_seconds: int = Field(description="Actual bucket resolution used in seconds")


# F4 schemas - Groups


class GroupBase(BaseModel):
    """Base group fields."""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    access_users: list[str] = Field(default_factory=list)
    auto_distribute_keys: bool = True


class GroupCreate(GroupBase):
    """Group creation request."""

    pass


class GroupResponse(GroupBase):
    """Group response with timestamps."""

    model_config = ConfigDict(from_attributes=True)

    created_at: datetime


# F4 schemas - SSH Keys


class SSHKeyBase(BaseModel):
    """Base SSH key fields."""

    user_name: str = Field(default="root", min_length=1, max_length=32)
    pubkey: str = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    algorithm: str = Field(default="ed25519", pattern=r"^(ed25519|rsa|ecdsa)$")

    @field_validator("pubkey")
    @classmethod
    def validate_pubkey_format(cls, v: str) -> str:
        """Validate pubkey starts with correct algorithm prefix."""
        if not v.startswith(("ssh-ed25519 ", "ssh-rsa ", "ecdsa-sha2-")):
            raise ValueError("pubkey must start with ssh-ed25519, ssh-rsa, or ecdsa-sha2-*")
        return v


class SSHKeyRegister(SSHKeyBase):
    """SSH key registration request from agent."""

    host_id: uuid.UUID


class SSHKeyResponse(SSHKeyBase):
    """SSH key response with full details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    created_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = None


# F4 schemas - Commands


class CommandBase(BaseModel):
    """Base command fields."""

    host_id: uuid.UUID
    issued_by: str = Field(min_length=1)
    command_type: str = Field(min_length=1, max_length=50)
    command_payload: dict[str, Any]
    server_signature: str = Field(min_length=1)
    agent_node_id: str | None = None


class CommandCreate(CommandBase):
    """Command creation request (server internal)."""

    human_approved: bool = False
    approved_by: str | None = None


class CommandAck(BaseModel):
    """Command acknowledgment from agent after execution."""

    command_id: uuid.UUID
    completed_at: datetime
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    rejected_reason: str | None = None


class CommandResponse(CommandBase):
    """Command response with full execution details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    issued_at: datetime
    completed_at: datetime | None = None
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_ms: int | None = None
    human_approved: bool
    approved_by: str | None = None
    rejected_reason: str | None = None


# F4 schemas - Agent Version


class AgentVersionInfo(BaseModel):
    """Agent version and API compatibility info.

    Used for parsing Sec-RP-Agent-Version header and version negotiation.
    """

    agent_version: str = Field(pattern=r"^\d+\.\d+\.\d+")
    api_compat_min: str = Field(pattern=r"^\d+\.\d+\.\d+")
    api_compat_max: str = Field(pattern=r"^\d+\.\d+\.\d+")

    @classmethod
    def from_header(cls, header: str) -> "AgentVersionInfo":
        """Parse from Sec-RP-Agent-Version header format.

        Format: "agent_version;min=X.Y.Z;max=X.Y.Z"
        Example: "0.5.2;min=0.5.0;max=0.6.0"
        """
        parts = header.split(";")
        if len(parts) != 3:
            raise ValueError("Invalid agent version header format")

        agent_version = parts[0].strip()
        min_match = re.match(r"min=(\d+\.\d+\.\d+)", parts[1].strip())
        max_match = re.match(r"max=(\d+\.\d+\.\d+)", parts[2].strip())

        if not min_match or not max_match:
            raise ValueError("Invalid API compatibility range format")

        return cls(
            agent_version=agent_version,
            api_compat_min=min_match.group(1),
            api_compat_max=max_match.group(1),
        )


# F5 schemas - Users


class UserBase(BaseModel):
    """Base user fields."""

    email: str = Field(min_length=1, max_length=255)
    name: str | None = None
    role: str = Field(default="viewer", pattern=r"^(admin|operator|viewer)$")
    accessible_groups: list[str] = Field(default_factory=list)
    avatar_url: str | None = None


class UserCreate(UserBase):
    """User creation request (internal)."""

    pocketid_sub: str = Field(min_length=1)


class UserUpdate(BaseModel):
    """User update request (partial)."""

    name: str | None = None
    role: str | None = Field(default=None, pattern=r"^(admin|operator|viewer)$")
    accessible_groups: list[str] | None = None
    avatar_url: str | None = None
    is_active: bool | None = None


class UserResponse(UserBase):
    """User response with full details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pocketid_sub: str
    created_at: datetime
    last_login_at: datetime | None = None
    is_active: bool


class MeResponse(BaseModel):
    """Current user info response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    role: str
    accessible_groups: list[str]
    avatar_url: str | None = None


# F7-6 schemas - Enrollment Links


class EnrollLinkRequest(BaseModel):
    """Magic-link enrollment request."""

    group: str = Field(default="default", max_length=100)
    hostname: str | None = Field(default=None, max_length=255)
    ttl_hours: int = Field(default=24, ge=1, le=168)  # max 7 days
    max_uses: int = Field(default=1, ge=1, le=100)


class EnrollLinkResponse(BaseModel):
    """Magic-link enrollment response."""

    token: str
    expires_at: datetime
    magic_url_unix: str
    magic_url_windows: str
    qr_code_svg: str


# F8-3 schemas - API Compatibility


class ServerInfoResponse(BaseModel):
    """Server info response for agent compatibility checks.

    Public endpoint (no auth) - agents call before connecting.
    See ADR-0008 Appendix G for version negotiation policy.
    """

    server_version: str = Field(description="Server API version (semver)")
    api_version: str = Field(default="v1", description="API prefix version")
    min_agent_version: str = Field(description="Minimum supported agent version")
    deprecated_agent_versions: list[str] = Field(
        description="Agent versions that trigger deprecation warnings"
    )
    features: list[str] = Field(
        description="List of supported feature flags (e.g. 'heartbeat', 'signed_commands')"
    )
    tailscale_ssh_supported: bool = Field(default=True)
    rustdesk_direct_ip_supported: bool = Field(default=True)
    sunshine_supported: bool = Field(default=True)
    max_metrics_window: str = Field(
        default="1y", description="Maximum time window for metrics queries"
    )
    metrics_retention_policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "heartbeat_raw": "90d",
            "metrics_downsampled_5m": "1y",
            "metrics_downsampled_1h": "5y",
        }
    )


class CompatMatrixEntry(BaseModel):
    """Agent version distribution entry."""

    agent_version: str
    host_count: int
    deprecated: bool
    compatible: bool


class CompatMatrixResponse(BaseModel):
    """Compatibility matrix showing agent version distribution across fleet."""

    server_version: str
    min_agent_version: str
    entries: list[CompatMatrixEntry]
    total_hosts: int


# F8 schemas - Canary deploy


class CanaryUpgradeRequest(BaseModel):
    """Request to initiate canary upgrade."""

    group: str = Field(description="Target group for upgrade")
    target_version: str = Field(pattern=r"^\d+\.\d+\.\d+", description="Target agent version")
    canary_host_id: uuid.UUID | None = Field(
        default=None,
        description="Specific host ID for canary (if None, selects lowest-criticality)",
    )
    observation_minutes: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Observation period after canary upgrade",
    )


class CanaryUpgradeResponse(BaseModel):
    """Response from canary upgrade initiation."""

    canary_id: uuid.UUID
    target_version: str
    canary_host_id: uuid.UUID
    canary_hostname: str
    group_name: str
    observation_minutes: int
    eta_minutes: int
    state: str


class CanaryStatus(BaseModel):
    """Status of a canary deploy."""

    id: uuid.UUID
    group_name: str
    target_version: str
    canary_host_id: uuid.UUID
    canary_hostname: str
    state: str  # pending, observing, propagating, complete, failed_rollback
    initiated_at: datetime
    observation_minutes: int
    canary_health_check_at: datetime | None
    propagation_started_at: datetime | None
    completed_at: datetime | None
    failed_reason: str | None
    initiated_by: str
    hosts_remaining: int
    hosts_upgraded: int


class SelfCheckRequest(BaseModel):
    """Self-check report from agent post-upgrade."""

    host_id: uuid.UUID
    agent_version: str
    upgrade_id: uuid.UUID | None = None
    status: str  # ok, failed
    errors: list[str] = Field(default_factory=list)


class SelfCheckResponse(BaseModel):
    """Response to self-check report."""

    acknowledged: bool
    canary_state_updated: bool = False
