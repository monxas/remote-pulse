"""Upgrade command - upgrade agent to new version or rollback."""

import asyncio
import click
import structlog

from rp.client import RPClient
from rp.config import load_config
from rp.upgrade import AgentUpgrader

logger = structlog.get_logger()


@click.command()
@click.argument("target_version", required=False)
@click.option("--rollback", is_flag=True, help="Rollback to N-1 version")
@click.option(
    "--dry-run", is_flag=True, help="Show what would happen without executing"
)
def upgrade(target_version: str | None, rollback: bool, dry_run: bool):
    """Upgrade agent to a new version, or rollback to previous.

    Examples:
        rp upgrade 0.2.0         # Upgrade to version 0.2.0
        rp upgrade --rollback    # Rollback to previous version
        rp upgrade 0.2.0 --dry-run  # Preview upgrade without executing
    """
    asyncio.run(_upgrade_impl(target_version, rollback, dry_run))


async def _upgrade_impl(target_version: str | None, rollback: bool, dry_run: bool):
    """Implementation of upgrade command."""

    # Load config
    try:
        config = load_config()
    except Exception as e:
        click.secho(f"Error: Failed to load config: {e}", fg="red")
        raise click.Abort()

    # Create client (F8-CANARY: RPClient constructor varies by phase; use new signature)
    client = RPClient(config=config)

    # Create upgrader
    upgrader = AgentUpgrader(client=client)

    if rollback:
        # Perform rollback
        click.echo("Initiating rollback to N-1 version...")
        result = await upgrader.rollback(reason="manual_cli")

        if result.success:
            click.secho(
                f"✓ Rollback successful: {result.from_version} → {result.to_version}",
                fg="green",
            )
            click.echo("\nService will restart momentarily.")
        else:
            click.secho("✗ Rollback failed", fg="red")
            for error in result.errors:
                click.echo(f"  - {error}")
            raise click.Abort()

    elif target_version:
        # Perform upgrade
        if dry_run:
            click.echo(f"[DRY RUN] Would upgrade to version {target_version}")
        else:
            click.echo(f"Upgrading to version {target_version}...")

        result = await upgrader.upgrade_to(target_version, dry_run=dry_run)

        if result.success:
            if result.rollback:
                click.secho(
                    f"⚠ Upgrade failed, rolled back to {result.old_version}",
                    fg="yellow",
                )
            else:
                click.secho(
                    f"✓ Upgrade successful: {result.old_version} → {result.new_version} ({result.duration_s:.1f}s)",
                    fg="green",
                )

            if result.errors:
                click.echo("\nWarnings:")
                for error in result.errors:
                    click.echo(f"  - {error}")
        else:
            click.secho("✗ Upgrade failed", fg="red")
            for error in result.errors:
                click.echo(f"  - {error}")
            raise click.Abort()

    else:
        # Show current versions
        click.echo("Current agent version information:\n")
        versions = upgrader.get_versions()

        click.echo(f"  Current:  {versions['current']}")
        if versions["previous"]:
            click.echo(f"  Previous: {versions['previous']}")
        else:
            click.echo("  Previous: (none)")

        if versions["available_versions"]:
            click.echo("\nAvailable versions:")
            for ver in versions["available_versions"][:5]:  # Show latest 5
                marker = " (current)" if ver == versions["current"] else ""
                click.echo(f"  - {ver}{marker}")
        else:
            click.echo("\nCould not fetch available versions from GitHub.")

        click.echo("\nUsage:")
        click.echo("  rp upgrade <version>     Upgrade to specific version")
        click.echo("  rp upgrade --rollback    Rollback to previous version")
