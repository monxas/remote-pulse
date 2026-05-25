"""SSH command with Tailscale SSH preferred and classic fallback."""

import asyncio
from typing import Optional

import click
import structlog

from rp.client import RPClient
from rp.config import load_config
from rp.ssh_wrapper import SSHWrapper

logger = structlog.get_logger(__name__)


@click.command()
@click.argument("target")
@click.argument("remote_cmd", nargs=-1)
@click.option("--user", default=None, help="Remote user (defaults to current user)")
@click.option("--port", default=None, type=int, help="SSH port (defaults to 22)")
@click.option(
    "--force-classic",
    is_flag=True,
    help="Skip Tailscale SSH, use classic SSH only",
)
@click.pass_context
def ssh(
    ctx: click.Context,
    target: str,
    remote_cmd: tuple[str, ...],
    user: Optional[str],
    port: Optional[int],
    force_classic: bool,
):
    """
    SSH to a host (Tailscale SSH preferred, classic fallback).

    Attempts Tailscale SSH first if available and enabled on target,
    falls back to classic SSH with managed key.

    Examples:

    \b
        rp ssh pmx-50
        rp ssh carmelo --user=ramon
        rp ssh lxc-280 -- systemctl status rp-server
        rp ssh pmx-51 --force-classic
    """
    asyncio.run(_ssh_async(target, remote_cmd, user, port, force_classic))


async def _ssh_async(
    target: str,
    remote_cmd: tuple[str, ...],
    user: Optional[str],
    port: Optional[int],
    force_classic: bool,
):
    """Async SSH wrapper execution."""
    try:
        # Load config to get server URL
        config = load_config()

        # Create client
        async with RPClient(config) as client:
            wrapper = SSHWrapper(client)

            # Convert remote_cmd tuple to list (or None if empty)
            cmd = list(remote_cmd) if remote_cmd else None

            # Connect
            exit_code = await wrapper.connect(
                target=target,
                command=cmd,
                user=user,
                port=port,
                force_classic=force_classic,
            )

            # Exit with same code as SSH
            raise SystemExit(exit_code)

    except FileNotFoundError as e:
        logger.error("config_not_found", error=str(e))
        click.echo(f"Error: {e}", err=True)
        click.echo("Run 'rp install' first to configure agent.", err=True)
        raise SystemExit(1)

    except Exception as e:
        logger.error("ssh_failed", error=str(e))
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
