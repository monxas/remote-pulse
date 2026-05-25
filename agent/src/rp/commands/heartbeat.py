"""Heartbeat command - send heartbeat to server."""

import asyncio
import sys

import click
import structlog

from rp.config import config_exists
from rp.daemon import run_once, main_daemon

logger = structlog.get_logger()


@click.command()
@click.option("--once", is_flag=True, help="Send single heartbeat and exit")
@click.option("--daemon", is_flag=True, help="Run as daemon (continuous loop)")
@click.option("--config-path", default=None, help="Config file path")
def heartbeat(once: bool, daemon: bool, config_path: str):
    """
    Send heartbeat to server.

    By default runs as daemon. Use --once for testing.
    """
    if not config_exists():
        click.echo("Error: Agent not installed. Run 'rp install' first.", err=True)
        sys.exit(1)

    # Setup logging
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if once:
        # Send single heartbeat
        try:
            asyncio.run(run_once(config_path))
            click.echo("✓ Heartbeat sent successfully")
        except Exception as e:
            logger.error("heartbeat failed", error=str(e))
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    elif daemon:
        # Run as daemon
        main_daemon()

    else:
        # Default to daemon mode
        click.echo("Starting daemon mode (Ctrl+C to stop)...")
        main_daemon()
