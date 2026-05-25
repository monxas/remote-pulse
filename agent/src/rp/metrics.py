"""Cross-platform metrics collection using psutil."""

import time
from typing import Optional

import psutil
import structlog

from rp import __version__
from rp.platform_detect import get_os

logger = structlog.get_logger()


class MetricsCollector:
    """Collects system metrics cross-platform."""

    def __init__(self):
        self.os_type = get_os()

    def collect_heartbeat_metrics(self) -> dict[str, any]:
        """
        Collect F1 minimal heartbeat metrics.

        Returns:
            Dict with cpu_pct, mem_pct, load_1m (Linux only), uptime_s, agent_version
        """
        metrics = {
            "agent_version": __version__,
            "agent_ts": time.time(),
        }

        # CPU percentage (1 second sample)
        try:
            metrics["cpu_pct"] = psutil.cpu_percent(interval=1.0)
        except Exception as e:
            logger.warning("failed to collect cpu_pct", error=str(e))
            metrics["cpu_pct"] = None

        # Memory percentage
        try:
            mem = psutil.virtual_memory()
            metrics["mem_pct"] = mem.percent
        except Exception as e:
            logger.warning("failed to collect mem_pct", error=str(e))
            metrics["mem_pct"] = None

        # Load average (Linux/macOS only)
        if self.os_type in ("linux", "macos"):
            try:
                load = psutil.getloadavg()
                metrics["load_1m"] = load[0]
            except Exception as e:
                logger.warning("failed to collect load_1m", error=str(e))
                metrics["load_1m"] = None
        else:
            metrics["load_1m"] = None

        # Uptime
        try:
            boot_time = psutil.boot_time()
            metrics["uptime_s"] = int(time.time() - boot_time)
        except Exception as e:
            logger.warning("failed to collect uptime_s", error=str(e))
            metrics["uptime_s"] = None

        return metrics

    def collect_detailed_metrics(self) -> dict[str, any]:
        """
        Collect detailed metrics for F3+ (disk, network, per-core CPU).

        This is a placeholder for future phases.
        """
        metrics = {}

        # Disk usage per partition
        try:
            disks = {}
            for partition in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disks[partition.mountpoint] = {
                        "used_pct": usage.percent,
                        "used_gb": usage.used / (1024**3),
                        "total_gb": usage.total / (1024**3),
                    }
                except PermissionError:
                    continue
            metrics["disk"] = disks
        except Exception as e:
            logger.warning("failed to collect disk metrics", error=str(e))

        # Network I/O
        try:
            net_io = psutil.net_io_counters(pernic=True)
            metrics["net"] = {
                iface: {
                    "bytes_sent": counters.bytes_sent,
                    "bytes_recv": counters.bytes_recv,
                }
                for iface, counters in net_io.items()
            }
        except Exception as e:
            logger.warning("failed to collect net metrics", error=str(e))

        # Per-core CPU
        try:
            per_cpu = psutil.cpu_percent(interval=0.5, percpu=True)
            metrics["cpu_per_core"] = {
                f"core_{i}": pct for i, pct in enumerate(per_cpu)
            }
        except Exception as e:
            logger.warning("failed to collect per-core cpu", error=str(e))

        return metrics
