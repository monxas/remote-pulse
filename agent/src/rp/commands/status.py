"""Status command - show agent status."""

import sys
from pathlib import Path

import click

from rp import __version__
from rp.config import config_exists, load_config, DEFAULT_CONFIG_PATH
from rp.platform_detect import get_platform_info


@click.command()
@click.option("--config-path", default=None, help="Config file path")
def status(config_path: str):
    """Show agent status and configuration."""
    config_file = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    if not config_exists():
        click.echo("Status: NOT INSTALLED")
        click.echo(f"Config file not found: {config_file}")
        click.echo()
        click.echo("Run 'rp install --token=<TOKEN>' to install agent.")
        sys.exit(1)

    # Load config
    try:
        config = load_config(config_file)
    except Exception as e:
        click.echo(f"Error loading config: {e}", err=True)
        sys.exit(1)

    # Get platform info
    platform_info = get_platform_info()

    # Display status
    click.echo("Remote-Pulse Agent Status")
    click.echo("=" * 50)
    click.echo(f"Agent Version:     {__version__}")
    click.echo(f"Status:            INSTALLED")
    click.echo()
    click.echo("Configuration:")
    click.echo(f"  Host ID:         {config.host_id}")
    click.echo(f"  Server URL:      {config.server_url}")
    click.echo(f"  Heartbeat:       {config.heartbeat_interval_s}s")
    if config.group:
        click.echo(f"  Group:           {config.group}")
    click.echo(f"  Config file:     {config_file}")
    click.echo()
    click.echo("Platform:")
    click.echo(f"  OS:              {platform_info['os']}")
    click.echo(f"  Architecture:    {platform_info['arch']}")
    click.echo(f"  Distribution:    {platform_info['distro']}")
    click.echo(f"  Kernel:          {platform_info['kernel']}")
    click.echo(f"  FQDN:            {platform_info['fqdn']}")
    click.echo(f"  Python:          {platform_info['python_version']}")
    click.echo()
    click.echo("Capabilities:")
    for cap, enabled in platform_info["capabilities"].items():
        status_icon = "✓" if enabled else "✗"
        click.echo(f"  {status_icon} {cap}")
    click.echo()
    click.echo("Daemon Status:     UNKNOWN (check with systemctl status remote-pulse)")
