"""Screen sharing command for RustDesk, Sunshine, and VNC."""

import asyncio

import click
import structlog

from rp.client import RPClient
from rp.config import load_config
from rp.screen import HostResolver, RustDeskLauncher, SunshineLauncher, VNCLauncher

logger = structlog.get_logger(__name__)


@click.command()
@click.argument("target")
@click.option(
    "--protocol",
    default="auto",
    type=click.Choice(["auto", "rustdesk", "sunshine", "vnc"], case_sensitive=False),
    help="Screen sharing protocol to use",
)
@click.option(
    "--no-wait",
    is_flag=True,
    help="Don't wait for client process to exit",
)
@click.pass_context
def screen(
    ctx: click.Context,
    target: str,
    protocol: str,
    no_wait: bool,
):
    """
    Open remote screen (RustDesk/Sunshine/VNC) to target host.

    Automatically selects best available protocol or uses specified protocol.
    Launches local client connecting to remote host via Tailscale.

    Examples:

    \b
        rp screen pmx-50
        rp screen carmelo --protocol=rustdesk
        rp screen ai-tagger --protocol=sunshine
        rp screen lxc-100 --protocol=vnc
        rp screen pmx-51 --no-wait
    """
    asyncio.run(_screen_async(target, protocol, no_wait))


async def _screen_async(target: str, protocol: str, no_wait: bool):
    """Async screen launcher."""
    try:
        # Load config
        config = load_config()

        # Create client
        async with RPClient(config) as client:
            resolver = HostResolver(client)

            # Resolve target
            click.echo(f"Resolving host '{target}'...")
            resolved = await resolver.resolve(target)

            click.echo(
                f"Connecting to {resolved.hostname} ({resolved.tailscale_ip})..."
            )

            # Determine protocol
            if protocol == "auto":
                selected_protocol = _select_protocol(resolved)
            else:
                selected_protocol = protocol

            click.echo(f"Using protocol: {selected_protocol}")

            # Launch appropriate client
            exit_code = await _launch_client(selected_protocol, resolved)

            if no_wait:
                click.echo(
                    f"Screen client launched in background (protocol: {selected_protocol})"
                )
                raise SystemExit(0)

            # Wait for client exit
            raise SystemExit(exit_code)

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    except Exception as e:
        logger.error("screen_failed", error=str(e))
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


def _select_protocol(resolved) -> str:
    """Auto-select best available protocol based on host capabilities."""
    caps = resolved.capabilities

    # Prefer RustDesk (most universal)
    if caps.get("rustdesk_password"):
        return "rustdesk"

    # Gaming/Windows hosts: Sunshine
    if caps.get("sunshine_enabled"):
        return "sunshine"

    # Linux fallback: VNC
    if caps.get("vnc_installed"):
        return "vnc"

    raise ValueError(
        f"Host '{resolved.hostname}' has no screen sharing capabilities enabled. "
        "Install RustDesk/Sunshine/VNC on the target host first."
    )


async def _launch_client(protocol: str, resolved) -> int:
    """Launch appropriate screen sharing client."""
    if protocol == "rustdesk":
        launcher = RustDeskLauncher()
        return await launcher.launch(resolved)

    elif protocol == "sunshine":
        launcher = SunshineLauncher()
        return await launcher.launch(resolved)

    elif protocol == "vnc":
        launcher = VNCLauncher()
        return await launcher.launch(resolved)

    else:
        raise ValueError(f"Unknown protocol: {protocol}")
