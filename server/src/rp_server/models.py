"""SQLAlchemy ORM models for Remote-Pulse server."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    type_annotation_map = {
        dict[str, Any]: JSONB,
        datetime: TIMESTAMP(timezone=True),
    }


class Host(Base):
    """Host inventory table."""

    __tablename__ = "hosts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    fqdn: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailscale_node_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    os: Mapped[str] = mapped_column(Text, nullable=False)
    arch: Mapped[str] = mapped_column(Text, nullable=False)
    distro: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_version: Mapped[str] = mapped_column(Text, nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    group_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    extra: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # Relationships
    ssh_keys: Mapped[list["SSHKey"]] = relationship(
        back_populates="host", cascade="all, delete-orphan"
    )


class Enrollment(Base):
    """Enrollment token tracking table."""

    __tablename__ = "enrollments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    token_jti: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    issued_by: Mapped[str] = mapped_column(Text, nullable=False)
    group_name: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"), nullable=False)
    used_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), nullable=False)
    used_by_host_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class Heartbeat(Base):
    """Heartbeat time-series table (TimescaleDB hypertable as of F3/002 migration)."""

    __tablename__ = "heartbeats"

    host_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        nullable=False,
        server_default=text("now()"),
    )
    agent_ts: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    cpu_pct: Mapped[float | None] = mapped_column(nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(nullable=True)
    load_1m: Mapped[float | None] = mapped_column(nullable=True)
    uptime_s: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(Text, nullable=True)


class MetricSample(Base):
    """Custom metric samples time-series table (TimescaleDB hypertable F3/002 migration).

    Stores arbitrary metrics beyond standard heartbeat fields.
    Examples: cpu_per_core.0, disk_used_pct./, net_rx_bps.eth0

    Note: Using composite PK for SQLAlchemy ORM requirement. TimescaleDB partitions on ts.
    """

    __tablename__ = "metric_samples"

    host_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        nullable=False,
        server_default=text("now()"),
    )
    metric: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    value: Mapped[float] = mapped_column(nullable=False)


class Group(Base):
    """Groups table for host organization and SSH key distribution.

    F4 schema. Groups control access policies and automatic SSH key distribution.
    """

    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_users: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::TEXT[]"),
    )
    auto_distribute_keys: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class SSHKey(Base):
    """SSH keys registered by agents for centralized lifecycle management.

    F4 schema. Keys are generated on hosts, registered in server inventory,
    distributed to authorized_keys via groups declaratively, and revocable.
    """

    __tablename__ = "ssh_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'root'"),
    )
    pubkey: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    algorithm: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    host: Mapped["Host"] = relationship(back_populates="ssh_keys")


class Command(Base):
    """Immutable audit log for remote command execution.

    F4 schema. Append-only table enforced by DB trigger. Records all commands
    issued to agents with signatures, approvals, and execution results.
    """

    __tablename__ = "commands"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id"),
        nullable=False,
    )
    issued_by: Mapped[str] = mapped_column(Text, nullable=False)
    command_type: Mapped[str] = mapped_column(Text, nullable=False)
    command_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    human_approved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    server_signature: Mapped[str] = mapped_column(Text, nullable=False)
    agent_node_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent modification of committed records (defense in depth)."""
        # Allow setting during construction (when _sa_instance_state not initialized)
        if hasattr(self, "_sa_instance_state"):
            # Check if object is persistent (already committed to DB)
            from sqlalchemy.orm import object_state

            state = object_state(self)
            if state.persistent or state.detached:
                raise RuntimeError(
                    "Cannot modify Command after commit - table is append-only audit log"
                )
        super().__setattr__(name, value)


class AgentVersion(Base):
    """Agent version compatibility tracking.

    F4 schema. Tracks agent version and API compatibility range for each host
    to support N-2 version skew tolerance and safe upgrades.
    """

    __tablename__ = "agent_versions"

    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_version: Mapped[str] = mapped_column(Text, nullable=False)
    api_compat_min: Mapped[str] = mapped_column(Text, nullable=False)
    api_compat_max: Mapped[str] = mapped_column(Text, nullable=False)
    last_check: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
