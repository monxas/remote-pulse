"""Daemon loop for heartbeat scheduler."""

import asyncio
import signal
import sys
from typing import Optional

import structlog

from rp.client import RPClient
from rp.config import load_config
from rp.metrics import MetricsCollector

logger = structlog.get_logger()


class HeartbeatDaemon:
    """Daemon for sending periodic heartbeats."""

    def __init__(self):
        self.running = False
        self.config = load_config()
        self.collector = MetricsCollector()
        self._task: Optional[asyncio.Task] = None

    def _setup_signal_handlers(self):
        """Setup graceful shutdown on SIGTERM/SIGINT."""

        def handle_signal(signum, frame):
            logger.info("received signal, shutting down", signal=signum)
            self.running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

    async def _heartbeat_loop(self):
        """Main heartbeat loop with exponential backoff on failure."""
        consecutive_failures = 0
        max_backoff = 60

        while self.running:
            try:
                # Collect metrics
                metrics = self.collector.collect_heartbeat_metrics()

                # Send to server
                async with RPClient(self.config) as client:
                    response = await client.heartbeat(metrics)

                logger.info(
                    "heartbeat sent",
                    host_id=self.config.host_id,
                    cpu_pct=metrics.get("cpu_pct"),
                    mem_pct=metrics.get("mem_pct"),
                )

                # Reset failure counter on success
                consecutive_failures = 0

                # Wait for next interval
                await asyncio.sleep(self.config.heartbeat_interval_s)

            except Exception as e:
                consecutive_failures += 1
                backoff = min(2**consecutive_failures, max_backoff)

                logger.error(
                    "heartbeat failed",
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                    backoff_s=backoff,
                )

                # Exponential backoff: 1s, 2s, 4s, 8s, ... up to 60s
                await asyncio.sleep(backoff)

    async def run(self):
        """Run daemon loop."""
        self.running = True
        self._setup_signal_handlers()

        logger.info(
            "starting heartbeat daemon",
            host_id=self.config.host_id,
            interval_s=self.config.heartbeat_interval_s,
        )

        try:
            await self._heartbeat_loop()
        except asyncio.CancelledError:
            logger.info("daemon cancelled")
        finally:
            logger.info("daemon stopped")

    def stop(self):
        """Stop the daemon."""
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()


async def run_once(config_path: Optional[str] = None):
    """
    Send single heartbeat and exit.

    Args:
        config_path: Optional config file path
    """
    from pathlib import Path

    config = load_config(Path(config_path) if config_path else None)
    collector = MetricsCollector()

    logger.info("sending single heartbeat", host_id=config.host_id)

    metrics = collector.collect_heartbeat_metrics()

    async with RPClient(config) as client:
        response = await client.heartbeat(metrics)

    logger.info("heartbeat sent successfully", response=response)


def main_daemon():
    """Entry point for daemon mode."""
    daemon = HeartbeatDaemon()

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        logger.info("interrupted by user")
        sys.exit(0)
