"""Add TimescaleDB hypertables and continuous aggregates

Revision ID: 002
Revises: 001
Create Date: 2026-05-25

ADR-0008 F3-1 + Apéndice B: Convert heartbeats to hypertable, create metric_samples
hypertable with continuous aggregate and retention policies.

IMPORTANT: Requires TimescaleDB extension installed:
    apt install timescaledb-2-postgresql-16
    (configured in ansible role remote_pulse_server)
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Upgrade: Add TimescaleDB hypertables and continuous aggregates.

    1. Enable TimescaleDB extension (idempotent)
    2. Convert existing heartbeats table to hypertable
    3. Create metric_samples hypertable
    4. Create continuous aggregate metric_samples_5min
    5. Add retention policies
    6. Create indexes
    """
    # 1. Enable TimescaleDB extension
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    # 2. Convert heartbeats to hypertable
    # Using if_not_exists=TRUE and migrate_data=TRUE to handle existing data
    # chunk_time_interval of 1 day per ADR Appendix B
    op.execute("""
        SELECT create_hypertable(
            'heartbeats',
            'ts',
            if_not_exists => TRUE,
            migrate_data => TRUE,
            chunk_time_interval => INTERVAL '1 day'
        );
    """)

    # 3. Create metric_samples table and hypertable
    # host_id: UUID reference to hosts
    # ts: server receive timestamp (source of truth)
    # metric: string identifier (e.g. "cpu_pct", "mem_pct", "disk_used_pct./", "net_rx_bps.eth0")
    # value: numeric metric value
    op.execute("""
        CREATE TABLE metric_samples (
            host_id UUID NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            metric TEXT NOT NULL,
            value DOUBLE PRECISION
        );
    """)

    op.execute("""
        SELECT create_hypertable(
            'metric_samples',
            'ts',
            chunk_time_interval => INTERVAL '1 day'
        );
    """)

    # 4. Create continuous aggregate for 5-minute buckets
    # Aggregates avg/max/min over 5min windows for 1-year retention
    op.execute("""
        CREATE MATERIALIZED VIEW metric_samples_5min
        WITH (timescaledb.continuous) AS
        SELECT
            host_id,
            metric,
            time_bucket('5 minutes', ts) AS bucket,
            avg(value) AS avg_val,
            max(value) AS max_val,
            min(value) AS min_val
        FROM metric_samples
        GROUP BY host_id, metric, bucket
        WITH NO DATA;
    """)

    # 5. Add retention policies
    # heartbeats: 90 days (per ADR §9)
    op.execute("""
        SELECT add_retention_policy('heartbeats', INTERVAL '90 days');
    """)

    # metric_samples: 30 days raw data
    op.execute("""
        SELECT add_retention_policy('metric_samples', INTERVAL '30 days');
    """)

    # metric_samples_5min: 365 days aggregated
    op.execute("""
        SELECT add_retention_policy('metric_samples_5min', INTERVAL '365 days');
    """)

    # 6. Create indexes for efficient sparkline queries
    # Index for metric_samples: composite on (host_id, metric, ts DESC)
    op.execute("""
        CREATE INDEX idx_metric_samples_host_metric_ts
        ON metric_samples(host_id, metric, ts DESC);
    """)


def downgrade() -> None:
    """
    Downgrade: Remove TimescaleDB hypertables and extensions.

    NOTE: Does not drop timescaledb extension itself (may be shared).
    """
    # Drop retention policies
    op.execute("SELECT remove_retention_policy('metric_samples_5min', if_exists => TRUE);")
    op.execute("SELECT remove_retention_policy('metric_samples', if_exists => TRUE);")
    op.execute("SELECT remove_retention_policy('heartbeats', if_exists => TRUE);")

    # Drop continuous aggregate
    op.execute("DROP MATERIALIZED VIEW IF EXISTS metric_samples_5min;")

    # Drop metric_samples table (hypertable wrapper drops automatically)
    op.execute("DROP TABLE IF EXISTS metric_samples;")

    # Convert heartbeats back to regular table is complex and destructive
    # For downgrade, we'll just log a warning - in practice, should restore from backup
    # op.execute("DROP TABLE heartbeats;")  # Would need to recreate as regular table

    # NOTE: Not dropping timescaledb extension as it may be used by other schemas
    # op.execute("DROP EXTENSION IF EXISTS timescaledb;")
