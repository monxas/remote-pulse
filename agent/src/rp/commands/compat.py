"""Compatibility status check command.

Shows current agent + server version compatibility.
"""

import asyncio
import sys

import click
from rich.console import Console
from rich.table import Table

from rp.compat import (
    AGENT_FEATURES,
    AGENT_VERSION,
    APICompatHandler,
    IncompatibleVersionError,
)
from rp.config import AgentConfig

console = Console()


@click.command("compat")
def compat_cmd():
    """Show current agent + server version compatibility.

    Fetches server info via /v1/server/info and displays:
    - Agent version
    - Server version
    - Compatibility status
    - Feature comparison
    """
    try:
        config = AgentConfig.load()
    except FileNotFoundError:
        console.print("[red]Agent not enrolled yet. Run 'rp install' first.[/red]")
        sys.exit(1)

    asyncio.run(_check_compat(config))


async def _check_compat(config: AgentConfig):
    """Async compat check logic."""
    compat_handler = APICompatHandler(config.server_url)

    console.print(f"\n[bold]Checking compatibility with {config.server_url}[/bold]\n")

    try:
        server_info = await compat_handler.check_handshake()

    except IncompatibleVersionError as e:
        console.print(f"[red bold]Incompatible versions:[/red bold] {e}")
        sys.exit(1)

    except Exception as e:
        console.print(f"[red]Failed to fetch server info:[/red] {e}")
        sys.exit(1)

    # Print version info
    console.print(f"[green]Agent:[/green]    {AGENT_VERSION}")
    console.print(f"[green]Server:[/green]   {server_info.server_version}\n")

    # Compatibility status
    status = "[green]✓ Compatible[/green]"
    console.print(f"Compatibility: {status}")
    console.print(f"Server min agent: {server_info.min_agent_version}")
    console.print(f"Agent min server: {compat_handler.AGENT_MIN_SERVER_VERSION}\n")

    # Feature comparison table
    table = Table(title="Feature Compatibility")
    table.add_column("Feature", style="cyan")
    table.add_column("Status", style="white")

    agent_features = set(AGENT_FEATURES)
    server_features = set(server_info.features)

    # Features both have
    common_features = agent_features & server_features
    for feature in sorted(common_features):
        table.add_row(feature, "[green]✓ Supported[/green]")

    # Features server has but agent doesn't
    server_only = server_features - agent_features
    for feature in sorted(server_only):
        table.add_row(feature, "[yellow]⚠ Server has, agent doesn't need[/yellow]")

    # Features agent expects but server doesn't have
    agent_only = agent_features - server_features
    for feature in sorted(agent_only):
        table.add_row(feature, "[red]✗ Server missing (degraded mode)[/red]")

    console.print(table)

    # Additional capabilities
    if server_info.tailscale_ssh_supported:
        console.print("\n[dim]Tailscale SSH:[/dim] Supported")
    if server_info.rustdesk_direct_ip_supported:
        console.print("[dim]RustDesk Direct IP:[/dim] Supported")
    if server_info.sunshine_supported:
        console.print("[dim]Sunshine (gaming-grade remote):[/dim] Supported")

    console.print(f"\n[dim]Max metrics window:[/dim] {server_info.max_metrics_window}")
