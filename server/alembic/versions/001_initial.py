"""Initial schema: hosts, enrollments, heartbeats

Revision ID: 001
Revises:
Create Date: 2026-05-25

F1 minimal schema. heartbeats and metric_samples created as normal tables
but designed for TimescaleDB hypertable conversion in F3.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("hostname", sa.Text(), nullable=False),
        sa.Column("fqdn", sa.Text(), nullable=True),
        sa.Column("tailscale_node_id", sa.Text(), nullable=True, unique=True),
        sa.Column("os", sa.Text(), nullable=False),
        sa.Column("arch", sa.Text(), nullable=False),
        sa.Column("distro", sa.Text(), nullable=True),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("group_name", sa.Text(), nullable=True),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "enrollments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("token_jti", sa.Text(), nullable=False, unique=True),
        sa.Column("issued_by", sa.Text(), nullable=False),
        sa.Column("group_name", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("max_uses", sa.SmallInteger(), server_default=sa.text("1")),
        sa.Column("used_count", sa.SmallInteger(), server_default=sa.text("0")),
        sa.Column("used_by_host_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["used_by_host_id"], ["hosts.id"]),
    )

    op.create_table(
        "heartbeats",
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ts", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("agent_ts", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cpu_pct", sa.REAL(), nullable=True),
        sa.Column("mem_pct", sa.REAL(), nullable=True),
        sa.Column("load_1m", sa.REAL(), nullable=True),
        sa.Column("uptime_s", sa.BigInteger(), nullable=True),
        sa.Column("agent_version", sa.Text(), nullable=True),
    )

    op.create_index("idx_heartbeats_host_ts", "heartbeats", ["host_id", sa.text("ts DESC")])


def downgrade() -> None:
    op.drop_index("idx_heartbeats_host_ts", table_name="heartbeats")
    op.drop_table("heartbeats")
    op.drop_table("enrollments")
    op.drop_table("hosts")
