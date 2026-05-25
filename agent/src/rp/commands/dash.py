"""Dashboard TUI command."""

import asyncio
import os

import click
import structlog

logger = structlog.get_logger(__name__)


@click.command()
@click.option(
    "--server",
    default=None,
    help="Server URL (overrides config)",
)
def dash(server: str | None) -> None:
    """
    Launch TUI dashboard for fleet monitoring.

    Interactive dashboard with host list, sparklines, and live updates.
    Press '?' for help, 'q' to quit.
    """
    from rp.config import load_config, DEFAULT_CONFIG_PATH
    from rp.dash.app import run_dashboard

    # Determine server URL
    if server:
        server_url = server
    elif "RP_SERVER_URL" in os.environ:
        server_url = os.environ["RP_SERVER_URL"]
    else:
        try:
            config = load_config()
            server_url = config.server_url
        except FileNotFoundError:
            click.echo(
                f"Error: Config not found at {DEFAULT_CONFIG_PATH}. "
                "Run 'rp install' first or use --server flag.",
                err=True,
            )
            raise click.Abort()
        except Exception as e:
            click.echo(f"Error loading config: {e}", err=True)
            raise click.Abort()

    logger.info("launching dashboard", server_url=server_url)

    try:
        asyncio.run(run_dashboard(server_url))
    except KeyboardInterrupt:
        logger.info("dashboard interrupted by user")
    except Exception as e:
        logger.error("dashboard crashed", error=str(e))
        click.echo(f"Dashboard error: {e}", err=True)
        raise click.Abort()
