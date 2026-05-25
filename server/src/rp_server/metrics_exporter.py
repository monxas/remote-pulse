"""Prometheus metrics exporter for Remote-Pulse server."""

from datetime import datetime, timezone

from prometheus_client import Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.models import Enrollment, Host, SSHKey

# Metrics: Server-side event counters
rp_enroll_total = Counter(
    "rp_enroll_total",
    "Agent enrollments",
    ["group", "result"],
)

rp_heartbeat_total = Counter(
    "rp_heartbeat_total",
    "Heartbeats received",
    ["group"],
)

rp_commands_executed_total = Counter(
    "rp_commands_executed_total",
    "Remote commands executed",
    ["command_type", "group", "result"],
)

rp_signature_invalid_total = Counter(
    "rp_signature_invalid_total",
    "Signature verification failures",
    ["host_id"],
)

rp_local_policy_deny_total = Counter(
    "rp_local_policy_deny_total",
    "Local-policy denies reported by agents",
    ["command_type", "group"],
)

# Gauges: Fleet-wide metrics (computed on-scrape)
rp_host_up = Gauge(
    "rp_host_up",
    "Host is reporting (last_seen < 180s)",
    ["host_id", "hostname", "group"],
)

rp_host_cpu_pct = Gauge(
    "rp_host_cpu_pct",
    "Latest CPU% per host",
    ["host_id", "hostname", "group"],
)

rp_host_mem_pct = Gauge(
    "rp_host_mem_pct",
    "Latest mem% per host",
    ["host_id", "hostname", "group"],
)

rp_host_load_1m = Gauge(
    "rp_host_load_1m",
    "Latest load 1m per host",
    ["host_id", "hostname", "group"],
)

rp_host_uptime_seconds = Gauge(
    "rp_host_uptime_seconds",
    "Host uptime in seconds",
    ["host_id", "hostname", "group"],
)

rp_host_last_seen_age_seconds = Gauge(
    "rp_host_last_seen_age_seconds",
    "Seconds since last heartbeat",
    ["host_id", "hostname", "group"],
)

rp_host_agent_version = Gauge(
    "rp_host_agent_version",
    "Agent version per host (1 always, labels carry value)",
    ["host_id", "hostname", "group", "version"],
)

# Server health metrics
rp_db_connections_active = Gauge(
    "rp_db_connections_active",
    "Active DB connections from pool",
)

rp_websocket_connections_active = Gauge(
    "rp_websocket_connections_active",
    "Active agent WS connections",
    ["channel"],
)

rp_enrollment_tokens_active = Gauge(
    "rp_enrollment_tokens_active",
    "Enrollment tokens not yet exhausted/expired",
)

rp_ssh_keys_total = Gauge(
    "rp_ssh_keys_total",
    "SSH keys registered",
    ["revoked"],
)

# HTTP request latency histogram
rp_http_request_duration_seconds = Histogram(
    "rp_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path", "status"],
)


# Counter helper functions for router instrumentation
def record_enroll_success(group: str) -> None:
    """Record successful enrollment."""
    rp_enroll_total.labels(group=group, result="success").inc()


def record_enroll_failure(group: str, reason: str) -> None:
    """Record failed enrollment."""
    rp_enroll_total.labels(group=group, result=f"fail_{reason}").inc()


def record_heartbeat(group: str) -> None:
    """Record heartbeat received."""
    rp_heartbeat_total.labels(group=group or "default").inc()


def record_command_executed(command_type: str, group: str, result: str) -> None:
    """Record command execution."""
    rp_commands_executed_total.labels(
        command_type=command_type,
        group=group or "default",
        result=result,
    ).inc()


def record_signature_invalid(host_id: str) -> None:
    """Record signature verification failure."""
    rp_signature_invalid_total.labels(host_id=host_id).inc()


def record_local_policy_deny(command_type: str, group: str) -> None:
    """Record local policy denial."""
    rp_local_policy_deny_total.labels(
        command_type=command_type,
        group=group or "default",
    ).inc()


async def refresh_fleet_gauges(db: AsyncSession) -> None:
    """Compute and update fleet-wide gauges from database.

    This is called on-demand during /metrics scrape to provide current state.
    Queries:
    - All hosts with last_seen_at
    - Latest heartbeat per host for metrics
    - Enrollment tokens active count
    - SSH keys counts by revoked status
    """
    now = datetime.now(timezone.utc)

    # Clear all host-specific gauges before refresh
    # (prometheus_client doesn't provide clear_all for labeled metrics,
    #  so we'll rely on setting current values and let stale labels expire)

    # Query all hosts
    stmt = select(Host)
    result = await db.execute(stmt)
    hosts = result.scalars().all()

    for host in hosts:
        host_id_str = str(host.id)
        hostname = host.hostname or "unknown"
        group = host.group_name or "default"

        # Compute last_seen age
        if host.last_seen_at:
            age_seconds = (now - host.last_seen_at).total_seconds()
            rp_host_last_seen_age_seconds.labels(
                host_id=host_id_str,
                hostname=hostname,
                group=group,
            ).set(age_seconds)

            # Host is "up" if last_seen < 180s
            is_up = 1 if age_seconds < 180 else 0
            rp_host_up.labels(
                host_id=host_id_str,
                hostname=hostname,
                group=group,
            ).set(is_up)
        else:
            # Never seen
            rp_host_up.labels(
                host_id=host_id_str,
                hostname=hostname,
                group=group,
            ).set(0)
            rp_host_last_seen_age_seconds.labels(
                host_id=host_id_str,
                hostname=hostname,
                group=group,
            ).set(-1)  # Indicator for "never seen"

        # Agent version (set to 1, version in label)
        rp_host_agent_version.labels(
            host_id=host_id_str,
            hostname=hostname,
            group=group,
            version=host.agent_version or "unknown",
        ).set(1)

    # Query latest heartbeat per host for metrics
    # Note: This is a simplified approach. For production, consider using
    # a window function or JOIN with subquery for efficient latest-per-host.
    # For F5, we'll query individually per host (acceptable for small fleets).
    from rp_server.models import Heartbeat

    for host in hosts:
        host_id_str = str(host.id)
        hostname = host.hostname or "unknown"
        group = host.group_name or "default"

        # Get latest heartbeat for this host
        hb_stmt = (
            select(Heartbeat)
            .where(Heartbeat.host_id == host.id)
            .order_by(Heartbeat.ts.desc())
            .limit(1)
        )
        hb_result = await db.execute(hb_stmt)
        latest_hb = hb_result.scalar_one_or_none()

        if latest_hb:
            if latest_hb.cpu_pct is not None:
                rp_host_cpu_pct.labels(
                    host_id=host_id_str,
                    hostname=hostname,
                    group=group,
                ).set(latest_hb.cpu_pct)

            if latest_hb.mem_pct is not None:
                rp_host_mem_pct.labels(
                    host_id=host_id_str,
                    hostname=hostname,
                    group=group,
                ).set(latest_hb.mem_pct)

            if latest_hb.load_1m is not None:
                rp_host_load_1m.labels(
                    host_id=host_id_str,
                    hostname=hostname,
                    group=group,
                ).set(latest_hb.load_1m)

            if latest_hb.uptime_s is not None:
                rp_host_uptime_seconds.labels(
                    host_id=host_id_str,
                    hostname=hostname,
                    group=group,
                ).set(latest_hb.uptime_s)

    # Enrollment tokens active (not exhausted and not expired)
    enroll_stmt = select(Enrollment).where(
        Enrollment.used_count < Enrollment.max_uses,
        Enrollment.expires_at > now,
    )
    enroll_result = await db.execute(enroll_stmt)
    active_tokens = len(enroll_result.scalars().all())
    rp_enrollment_tokens_active.set(active_tokens)

    # SSH keys counts
    ssh_stmt_active = select(SSHKey).where(SSHKey.revoked_at.is_(None))
    ssh_result_active = await db.execute(ssh_stmt_active)
    active_keys = len(ssh_result_active.scalars().all())
    rp_ssh_keys_total.labels(revoked="false").set(active_keys)

    ssh_stmt_revoked = select(SSHKey).where(SSHKey.revoked_at.is_not(None))
    ssh_result_revoked = await db.execute(ssh_stmt_revoked)
    revoked_keys = len(ssh_result_revoked.scalars().all())
    rp_ssh_keys_total.labels(revoked="true").set(revoked_keys)


def get_metrics_output() -> bytes:
    """Generate Prometheus metrics output in text exposition format."""
    return generate_latest()


def get_content_type() -> str:
    """Return Prometheus content type."""
    return CONTENT_TYPE_LATEST
