"""Daemon loops for heartbeat + remote command execution (Phase 2.5).

The daemon runs two cooperative asyncio tasks:

* :py:meth:`HeartbeatDaemon._heartbeat_loop` — periodic metrics push,
  unchanged from v1.0.
* :py:meth:`HeartbeatDaemon._command_loop` — pulls approved commands
  from the server, executes them locally, and posts results back. New
  in Phase 2.5 to close the exec-loop gap.

Both loops share the same ``self.running`` flag so a single SIGTERM cleanly
shuts down the whole agent. ``asyncio.gather(..., return_exceptions=True)``
makes sure one loop crashing doesn't take the other down silently.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

from rp.client import RPClient
from rp.commands.runner import RemoteCommand, execute_remote_command
from rp.config import load_config
from rp.metrics import MetricsCollector

logger = structlog.get_logger()


class HeartbeatDaemon:
    """Daemon running the heartbeat + command-execution loops."""

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
                    await client.heartbeat(metrics)

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

    async def _command_loop(self):
        """Phase 2.5 — poll for approved commands and execute them.

        Behaviour:
          * polls every ``config.command_poll_interval_s`` (default 5s)
          * runs each pending command via
            :func:`rp.commands.runner.execute_remote_command`
          * POSTs the result back; the server's idempotent UPDATE means
            a retried submission after a crash is safe (409 just means
            "already recorded, move on")
          * on any unhandled error, applies bounded exponential back-off
            up to 60s so a flapping server doesn't busy-loop the agent

        The loop swallows per-command exceptions so a single broken
        command doesn't poison the loop for the rest of the batch.
        """
        consecutive_failures = 0
        max_backoff = 60
        poll_interval = self.config.command_poll_interval_s or 5

        while self.running:
            try:
                async with RPClient(self.config) as client:
                    pending = await client.poll_commands()

                    for raw in pending:
                        try:
                            cmd = RemoteCommand.from_dict(raw)
                        except (KeyError, TypeError) as exc:
                            logger.warning(
                                "skipping malformed pending command",
                                error=str(exc),
                                raw=raw,
                            )
                            continue

                        logger.info(
                            "executing remote command",
                            id=cmd.id,
                            type=cmd.command_type,
                        )

                        start = time.monotonic()
                        try:
                            result = await execute_remote_command(cmd)
                        except Exception as exc:
                            # Defensive: runner shouldn't raise, but if it
                            # does we still want to report something so the
                            # dashboard isn't stuck on "approved".
                            logger.exception(
                                "command runner crashed",
                                id=cmd.id,
                                type=cmd.command_type,
                            )
                            duration_ms = int((time.monotonic() - start) * 1000)
                            await self._report_result(
                                client,
                                cmd.id,
                                exit_code=None,
                                stdout="",
                                stderr=f"agent runner crash: {exc!s}",
                                duration_ms=duration_ms,
                                rejected_reason="runner_exception",
                            )
                            continue

                        duration_ms = int((time.monotonic() - start) * 1000)
                        await self._report_result(
                            client,
                            cmd.id,
                            exit_code=result.exit_code,
                            stdout=result.stdout or "",
                            stderr=result.stderr or "",
                            duration_ms=duration_ms,
                            rejected_reason=result.rejected_reason,
                        )

                consecutive_failures = 0
                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_failures += 1
                backoff = min(2**consecutive_failures, max_backoff)
                logger.warning(
                    "command loop iteration failed",
                    error=str(e),
                    consecutive=consecutive_failures,
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)

    async def _report_result(
        self,
        client: RPClient,
        command_id: str,
        *,
        exit_code: Optional[int],
        stdout: str,
        stderr: str,
        duration_ms: int,
        rejected_reason: Optional[str],
    ) -> None:
        """POST a result, logging but swallowing transport errors.

        A failed POST is recoverable: the command stays "pending" on the
        server side and the next poll cycle will pick it up again. The
        server's idempotency guard (409 on completed commands) means a
        successful POST followed by a crash-then-retry is safe.
        """
        try:
            await client.post_command_result(
                command_id,
                {
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "duration_ms": duration_ms,
                    "agent_ts": datetime.now(timezone.utc).isoformat(),
                    "rejected_reason": rejected_reason,
                },
            )
            logger.info(
                "command result posted",
                command_id=command_id,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.error(
                "failed to post command result; will be retried on next poll",
                command_id=command_id,
                error=str(exc),
            )

    async def run(self):
        """Run heartbeat + command-execution loops concurrently."""
        self.running = True
        self._setup_signal_handlers()

        logger.info(
            "starting daemon",
            host_id=self.config.host_id,
            heartbeat_interval_s=self.config.heartbeat_interval_s,
            command_poll_interval_s=self.config.command_poll_interval_s,
        )

        try:
            # return_exceptions=True so one loop crashing doesn't cancel
            # the other (we want heartbeat to keep flowing even if command
            # exec hits a bug, and vice versa).
            await asyncio.gather(
                self._heartbeat_loop(),
                self._command_loop(),
                return_exceptions=True,
            )
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
