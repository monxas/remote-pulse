"""
Example usage of Remote-Pulse agent components.

This demonstrates the agent flow without requiring a real server.
"""

import asyncio

from rp.metrics import MetricsCollector
from rp.platform_detect import get_platform_info, get_host_fingerprint


def example_platform_detection():
    """Example: Platform detection."""
    print("=== Platform Detection ===")
    info = get_platform_info()

    print(f"OS: {info['os']}")
    print(f"Architecture: {info['arch']}")
    print(f"Distribution: {info['distro']}")
    print(f"Kernel: {info['kernel']}")
    print(f"FQDN: {info['fqdn']}")
    print(f"Python: {info['python_version']}")
    print("\nCapabilities:")
    for cap, enabled in info["capabilities"].items():
        print(f"  {'✓' if enabled else '✗'} {cap}")

    print(f"\nHost Fingerprint: {get_host_fingerprint()[:16]}...")
    print()


def example_metrics_collection():
    """Example: Metrics collection."""
    print("=== Metrics Collection ===")
    collector = MetricsCollector()

    # Collect heartbeat metrics
    metrics = collector.collect_heartbeat_metrics()
    print(f"Agent Version: {metrics['agent_version']}")
    print(f"CPU Usage: {metrics['cpu_pct']:.1f}%")
    print(f"Memory Usage: {metrics['mem_pct']:.1f}%")

    if metrics["load_1m"] is not None:
        print(f"Load Average (1m): {metrics['load_1m']:.2f}")

    print(f"Uptime: {metrics['uptime_s'] // 3600}h {(metrics['uptime_s'] % 3600) // 60}m")
    print()


async def example_heartbeat_simulation():
    """Example: Simulated heartbeat (without real server)."""
    print("=== Simulated Heartbeat ===")
    collector = MetricsCollector()

    print("Collecting metrics (1s CPU sample)...")
    metrics = collector.collect_heartbeat_metrics()

    print("\nPayload that would be sent to server:")
    print({
        "host_id": "example-host-123",
        "metrics": {
            "cpu_pct": metrics["cpu_pct"],
            "mem_pct": metrics["mem_pct"],
            "load_1m": metrics["load_1m"],
            "uptime_s": metrics["uptime_s"],
            "agent_version": metrics["agent_version"],
        },
    })
    print()


def main():
    """Run all examples."""
    print("Remote-Pulse Agent Examples\n")

    example_platform_detection()
    example_metrics_collection()
    asyncio.run(example_heartbeat_simulation())

    print("Done! These components work together in the 'rp' CLI.")


if __name__ == "__main__":
    main()
