"""SQLAlchemy ORM models for Remote-Pulse server."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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
    """Heartbeat time-series table (will become TimescaleDB hypertable in F3)."""

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
