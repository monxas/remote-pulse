"""Tests for metrics collection."""

from rp.metrics import MetricsCollector


def test_collect_heartbeat_metrics():
    """Test basic heartbeat metrics collection."""
    collector = MetricsCollector()
    metrics = collector.collect_heartbeat_metrics()

    # Check required fields
    assert "agent_version" in metrics
    assert "agent_ts" in metrics
    assert "cpu_pct" in metrics
    assert "mem_pct" in metrics
    assert "uptime_s" in metrics

    # Check types
    assert isinstance(metrics["agent_version"], str)
    assert isinstance(metrics["agent_ts"], float)

    # CPU and mem should be percentages (or None if collection failed)
    if metrics["cpu_pct"] is not None:
        assert 0 <= metrics["cpu_pct"] <= 100

    if metrics["mem_pct"] is not None:
        assert 0 <= metrics["mem_pct"] <= 100

    # Uptime should be positive
    if metrics["uptime_s"] is not None:
        assert metrics["uptime_s"] > 0


def test_collect_detailed_metrics():
    """Test detailed metrics collection (F3+ feature)."""
    collector = MetricsCollector()
    metrics = collector.collect_detailed_metrics()

    # Should return dict (even if empty on some platforms)
    assert isinstance(metrics, dict)
