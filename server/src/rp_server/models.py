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
    # Short, memorable enrollment code (e.g. ``K7MX3F``) — alphabet without
    # visually-confusable characters, see ``rp_server.auth.SHORT_CODE_ALPHABET``.
    # NULL on rows created before the alembic 011 migration; new rows always
    # populate it. Uniqueness is enforced via a partial unique index defined
    # in 011 (only active rows participate, so once a code expires or hits
    # ``max_uses`` it could theoretically be reused — see migration docstring
    # for the trade-off).
    short_code: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        ForeignKey("hosts.id", ondelete="CASCADE"),
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
    # F4-6: Telegram approval flow
    approval_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        nullable=True,
    )
    approval_requested_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    approval_responded_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent modification of committed records (defense in depth).

        Allow assignment during ORM hydration (loading from DB) and during
        new-instance construction; raise only on user-attempted mutation
        of a persistent or detached instance.
        """
        # Allow setting private SQLAlchemy state directly.
        if name.startswith("_sa_"):
            super().__setattr__(name, value)
            return

        sa_state = getattr(self, "_sa_instance_state", None)
        if sa_state is not None:
            # During hydration from DB rows, SQLAlchemy sets attributes; allow.
            if not sa_state.is_instance:  # pragma: no cover — defensive
                super().__setattr__(name, value)
                return
            if sa_state.persistent or sa_state.detached:
                raise RuntimeError(
                    "Cannot modify Command after commit — table is append-only audit log"
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


class User(Base):
    """User accounts for web dashboard access via PocketID OIDC.

    F5 schema. Users are synced from PocketID IdP and have role-based access
    with group filtering for multi-tenant fleet visibility.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pocketid_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'viewer'"),
    )
    accessible_groups: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::TEXT[]"),
    )
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )


class UserPermission(Base):
    """Row-level per-action grant for a dashboard user.

    Sits below ``users.role`` (admin / operator / viewer) and
    ``users.accessible_groups`` (group-level visibility): an explicit row
    here grants a specific action (e.g. ``command.issue``,
    ``command.approve``, ``host.delete``, ``enroll.create``) on a scope
    (group name pattern or ``*``).

    Admins (``users.role == 'admin'``) are implicitly granted every action
    and don't need rows here — the permissions module short-circuits.
    """

    __tablename__ = "user_permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'*'"),
    )
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class CanaryDeploy(Base):
    """Canary deployment tracking for agent upgrades.

    F8 schema. Tracks canary deploy state machine:
    pending → observing → propagating → complete | failed_rollback
    """

    __tablename__ = "canary_deploys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    group_name: Mapped[str] = mapped_column(Text, nullable=False)
    target_version: Mapped[str] = mapped_column(Text, nullable=False)
    canary_host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    initiated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    observation_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("10"),
    )
    canary_health_check_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    propagation_started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    initiated_by: Mapped[str] = mapped_column(Text, nullable=False)


class AuditEvent(Base):
    """Server-side audit trail for settings + ACL mutations.

    Complements the synthetic ``/v1/dash/audit`` timeline built from
    ``commands`` / ``hosts`` / ``enrollments`` with a real append-only log
    for events that don't have a natural home in those domain tables —
    chiefly settings mutations (group/user CRUD via ``/v1/dash/settings``).

    Rows are written inside the same transaction as the mutation they
    describe, so either both land or neither does. ``payload`` carries
    structured before/after data for updates and the seed data for
    creates/deletes.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
