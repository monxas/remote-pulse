"""Admin CLI helper for Remote-Pulse server (F4).

Invoke as: uv run python -m rp_server.admin <command>
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import structlog
import yaml
from jsonschema import ValidationError, validate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from tabulate import tabulate

from rp_server.config import settings
from rp_server.models import Group, SSHKey

logger = structlog.get_logger(__name__)


# Database setup for CLI
engine = create_async_engine(settings.database_url, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncSession:
    """Get database session for CLI commands."""
    async with async_session() as session:
        return session


def load_groups_config() -> dict[str, Any]:
    """Load and validate groups.yml configuration.

    Returns:
        Parsed groups configuration

    Raises:
        click.ClickException: If config invalid or missing
    """
    config_path = Path(__file__).parent.parent.parent / "config" / "groups.yml"
    schema_path = Path(__file__).parent.parent.parent / "config" / "groups.schema.json"

    if not config_path.exists():
        raise click.ClickException(f"Config file not found: {config_path}")

    if not schema_path.exists():
        raise click.ClickException(f"Schema file not found: {schema_path}")

    # Load config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Load schema
    with open(schema_path) as f:
        schema = json.load(f)

    # Validate
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        raise click.ClickException(f"Invalid config: {e.message}") from e

    return config


@click.group()
def cli():
    """Remote-Pulse server admin CLI."""
    pass


@cli.group()
def groups():
    """Group management commands."""
    pass


@groups.command()
def apply():
    """Apply groups.yml configuration to database.

    Upserts groups from config file. Does not delete groups not in config.
    """

    async def _apply():
        config = load_groups_config()
        async with async_session() as session:
            for name, data in config["groups"].items():
                stmt = select(Group).where(Group.name == name)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # Update
                    existing.description = data["description"]
                    existing.access_users = data["access_users"]
                    existing.auto_distribute_keys = data["auto_distribute_keys"]
                    click.echo(f"Updated group: {name}")
                else:
                    # Create
                    new_group = Group(
                        name=name,
                        description=data["description"],
                        access_users=data["access_users"],
                        auto_distribute_keys=data["auto_distribute_keys"],
                    )
                    session.add(new_group)
                    click.echo(f"Created group: {name}")

            await session.commit()
            click.echo(f"\n✓ Applied {len(config['groups'])} groups")

    asyncio.run(_apply())


@groups.command("list")
def list_groups():
    """List all groups from database."""

    async def _list():
        async with async_session() as session:
            stmt = select(Group).order_by(Group.name)
            result = await session.execute(stmt)
            groups_list = result.scalars().all()

            if not groups_list:
                click.echo("No groups found")
                return

            table = []
            for g in groups_list:
                table.append(
                    [
                        g.name,
                        g.description or "",
                        ", ".join(g.access_users) if g.access_users else "",
                        "Yes" if g.auto_distribute_keys else "No",
                        g.created_at.strftime("%Y-%m-%d"),
                    ]
                )

            click.echo(
                tabulate(
                    table,
                    headers=["Name", "Description", "Access Users", "Auto Dist", "Created"],
                    tablefmt="simple",
                )
            )

    asyncio.run(_list())


@cli.group()
def keys():
    """SSH key management commands."""
    pass


@keys.command("list")
@click.option("--group", help="Filter by group name")
@click.option("--include-revoked", is_flag=True, help="Include revoked keys")
def list_keys(group: str | None, include_revoked: bool):
    """List SSH keys."""

    async def _list():
        async with async_session() as session:
            stmt = select(SSHKey)

            if group:
                from rp_server.models import Host

                stmt = stmt.join(Host, SSHKey.host_id == Host.id).where(Host.group_name == group)

            if not include_revoked:
                stmt = stmt.where(SSHKey.revoked_at.is_(None))

            stmt = stmt.order_by(SSHKey.created_at.desc())

            result = await session.execute(stmt)
            keys_list = result.scalars().all()

            if not keys_list:
                click.echo("No keys found")
                return

            table = []
            for k in keys_list:
                status = "REVOKED" if k.revoked_at else "active"
                table.append(
                    [
                        k.fingerprint,
                        str(k.host_id)[:8],
                        k.user_name,
                        k.algorithm,
                        status,
                        k.created_at.strftime("%Y-%m-%d"),
                    ]
                )

            click.echo(
                tabulate(
                    table,
                    headers=["Fingerprint", "Host", "User", "Algo", "Status", "Created"],
                    tablefmt="simple",
                )
            )

    asyncio.run(_list())


@keys.command("revoke")
@click.argument("fingerprint")
@click.option("--reason", required=True, help="Revocation reason")
def revoke_key(fingerprint: str, reason: str):
    """Revoke an SSH key."""

    async def _revoke():
        async with async_session() as session:
            stmt = select(SSHKey).where(SSHKey.fingerprint == fingerprint)
            result = await session.execute(stmt)
            key = result.scalar_one_or_none()

            if not key:
                raise click.ClickException(f"Key {fingerprint} not found")

            if key.revoked_at:
                raise click.ClickException(f"Key already revoked at {key.revoked_at}")

            key.revoked_at = datetime.utcnow()
            key.revoked_reason = reason
            await session.commit()

            click.echo(f"✓ Revoked key {fingerprint}")
            click.echo(f"  Reason: {reason}")

    asyncio.run(_revoke())


if __name__ == "__main__":
    cli()
