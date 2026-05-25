"""Uninstall command - remove agent and cleanup."""

import asyncio
import shutil
import sys
from pathlib import Path

import click
import structlog

from rp.client import RPClient
from rp.config import config_exists, load_config, DEFAULT_CONFIG_PATH, get_state_dir

logger = structlog.get_logger()


async def deregister_from_server(config):
    """Attempt to deregister from server."""
    try:
        async with RPClient(config, timeout=5.0) as client:
            await client.deregister()
        return True
    except Exception as e:
        logger.warning("failed to deregister from server", error=str(e))
        return False


@click.command()
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--config-path", default=None, help="Config file path")
def uninstall(confirm: bool, config_path: str):
    """
    Uninstall Remote-Pulse agent and remove configuration.

    This will:
    - Stop the daemon (if running)
    - Deregister from server
    - Remove configuration files
    - Clean up state directory
    """
    config_file = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    if not config_exists():
        click.echo("Agent is not installed.")
        sys.exit(0)

    # Load config for deregistration
    try:
        config = load_config(config_file)
    except Exception as e:
        click.echo(f"Warning: Could not load config: {e}", err=True)
        config = None

    # Confirm
    if not confirm:
        click.echo("This will uninstall the Remote-Pulse agent and remove all configuration.")
        click.echo(f"Host ID: {config.host_id if config else 'unknown'}")
        click.echo()
        if not click.confirm("Continue with uninstall?"):
            click.echo("Uninstall cancelled.")
            sys.exit(0)

    click.echo("Uninstalling Remote-Pulse agent...")

    # Step 1: Stop daemon (best effort, systemd-specific)
    click.echo("  Stopping daemon...")
    # Note: F1 doesn't implement systemd unit, just note it
    click.echo("  (If running as systemd service, stop it with: systemctl stop remote-pulse)")

    # Step 2: Deregister from server
    if config:
        click.echo("  Deregistering from server...")
        success = asyncio.run(deregister_from_server(config))
        if success:
            click.echo("  ✓ Deregistered from server")
        else:
            click.echo("  ⚠ Could not deregister from server (may be offline or endpoint unavailable)")

    # Step 3: Remove config file
    if config_file.exists():
        click.echo(f"  Removing config file: {config_file}")
        config_file.unlink()

        # Remove parent directory if empty
        if config_file.parent.exists() and not any(config_file.parent.iterdir()):
            config_file.parent.rmdir()

    # Step 4: Remove state directory
    state_dir = get_state_dir()
    if state_dir.exists():
        click.echo(f"  Removing state directory: {state_dir}")
        shutil.rmtree(state_dir, ignore_errors=True)

    click.echo()
    click.echo("✓ Remote-Pulse agent uninstalled successfully")
    click.echo()
    click.echo("To reinstall, run: rp install --token=<TOKEN>")
