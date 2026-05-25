"""Install command - enroll agent with server."""

import socket
import sys
from pathlib import Path
from typing import Optional

import click
import httpx
import structlog

from rp.config import AgentConfig, save_config, DEFAULT_CONFIG_PATH
from rp.platform_detect import get_host_fingerprint, get_platform_info

logger = structlog.get_logger()


@click.command()
@click.option("--token", required=True, help="Enrollment JWT token")
@click.option("--server", default="https://rp.monxas.casa", help="Server URL")
@click.option("--hostname", default=None, help="Host name (default: auto-detect)")
@click.option("--group", default=None, help="Host group")
@click.option("--config-path", default=None, help="Config file path")
def install(
    token: str,
    server: str,
    hostname: Optional[str],
    group: Optional[str],
    config_path: Optional[str],
):
    """
    Install and register Remote-Pulse agent.

    Enrolls this host with the server and writes configuration to /etc/rp/config.toml.
    """
    # Auto-detect hostname if not provided
    if hostname is None:
        hostname = socket.gethostname().split(".")[0]

    # Get platform info and fingerprint
    platform_info = get_platform_info()
    host_fingerprint = get_host_fingerprint()

    logger.info(
        "enrolling agent",
        hostname=hostname,
        server=server,
        group=group,
        os=platform_info["os"],
        arch=platform_info["arch"],
    )

    # Enroll with server (synchronous for simplicity)
    try:
        client = httpx.Client(
            base_url=server,
            timeout=30.0,
            headers={"User-Agent": "remote-pulse-agent/0.1.0"},
        )

        # Match the EnrollRequest schema in server/.../schemas.py:
        # flat fields, not a nested `platform` object.
        from rp import __version__ as agent_version

        enroll_payload = {
            "token": token,
            "hostname": hostname,
            "host_fingerprint": host_fingerprint,
            "group": group or "default",
            "os": platform_info["os"],
            "arch": platform_info["arch"],
            "distro": platform_info.get("distro"),
            "agent_version": agent_version,
        }
        response = client.post("/v1/enroll", json=enroll_payload)

        response.raise_for_status()
        data = response.json()

        client.close()

    except httpx.HTTPError as e:
        logger.error("enrollment failed", error=str(e))
        click.echo(f"Error: Enrollment failed: {e}", err=True)
        sys.exit(1)

    # Extract response
    host_id = data.get("host_id")
    agent_config = data.get("agent_config", {})

    if not host_id:
        click.echo("Error: Server did not return host_id", err=True)
        sys.exit(1)

    # Create config
    config = AgentConfig(
        host_id=host_id,
        server_url=server,
        heartbeat_interval_s=agent_config.get("heartbeat_interval_s", 30),
        group=group,
    )

    # Save config
    config_file = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    try:
        save_config(config, config_file)
    except PermissionError:
        click.echo(
            f"Error: Permission denied writing to {config_file}. "
            "Run with sudo or adjust permissions.",
            err=True,
        )
        sys.exit(1)

    click.echo(f"✓ Remote-Pulse installed. Host '{hostname}' registered.")
    click.echo(f"  Host ID: {host_id}")
    click.echo(f"  Config: {config_file}")
    click.echo(f"  Server: {server}")
    click.echo()
    click.echo("Next steps:")
    click.echo("  - Run 'rp status' to check agent state")
    click.echo("  - Run 'rp heartbeat --once' to send test heartbeat")
    click.echo("  - Enable systemd service for automatic heartbeats")
