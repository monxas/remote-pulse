"""Pydantic request/response schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    # F2: tailscale_authkey will be added here


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
