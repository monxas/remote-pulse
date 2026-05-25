"""Remote exec command (audited via F4-4 signed commands)."""

import asyncio

import click
import structlog

from rp.client import RPClient
from rp.config import load_config

logger = structlog.get_logger(__name__)


@click.command("exec")
@click.argument("target")
@click.argument("remote_cmd", nargs=-1, required=True)
@click.option("--timeout", default=60, type=int, help="Command timeout in seconds")
@click.option(
    "--parallel",
    is_flag=True,
    help="When target is @group, run in parallel (default: sequential)",
)
@click.pass_context
def exec_(
    ctx: click.Context,
    target: str,
    remote_cmd: tuple[str, ...],
    timeout: int,
    parallel: bool,
):
    """
    Execute remote command on host or @group (audited via server API).

    Sends signed command via server's /v1/admin/commands endpoint (F4-4).
    Requires F4-4 (signed commands) and F4-6 (approval) for prod/iarq groups.

    Examples:

    \b
        rp exec pmx-50 -- systemctl status caddy
        rp exec @homelab -- uptime
        rp exec @prod -- apt update --timeout=120
        rp exec @family -- df -h --parallel
    """
    asyncio.run(_exec_async(target, remote_cmd, timeout, parallel))


async def _exec_async(
    target: str, remote_cmd: tuple[str, ...], timeout: int, parallel: bool
):
    """Async exec implementation."""
    try:
        # Load config
        config = load_config()

        # Create client
        async with RPClient(config) as client:
            # Check if F4-4 endpoint available
            click.echo(f"Sending command to {target}: {' '.join(remote_cmd)}")

            # Prepare command payload
            payload = {
                "target": target,
                "command": list(remote_cmd),
                "command_type": "exec_shell",
                "timeout": timeout,
                "parallel": parallel,
            }

            try:
                # POST /v1/admin/commands (F4-4 endpoint)
                response = await client.post("/v1/admin/commands", json=payload)
                response.raise_for_status()

                data = response.json()
                command_id = data.get("command_id")

                click.echo(f"Command submitted: {command_id}")
                click.echo(
                    f"Status: {data.get('status', 'pending')} (check logs for execution)"
                )

                # For prod/iarq groups, mention approval required
                if target.startswith("@") and target in ["@prod", "@iarq"]:
                    click.echo(
                        "\nNote: Command requires Telegram approval (F4-6) for sensitive groups."
                    )

                raise SystemExit(0)

            except Exception as e:
                # Check if endpoint not available (F4-4 not deployed yet)
                if "404" in str(e) or "not found" in str(e).lower():
                    click.echo(
                        "Error: Remote exec requires F4-4 (signed commands) + F4-6 (approval) endpoints.",
                        err=True,
                    )
                    click.echo(
                        "These features are not yet deployed on the server.", err=True
                    )
                    raise SystemExit(1)

                raise

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("Run 'rp install' first to configure agent.", err=True)
        raise SystemExit(1)

    except Exception as e:
        logger.error("exec_failed", error=str(e))
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
