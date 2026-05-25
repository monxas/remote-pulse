"""SSH key lifecycle CLI commands (F4)."""

import asyncio
import sys
import uuid

import click
import structlog

from rp.client import RPClient
from rp.config import load_config
from rp.ssh_keys import (
    HOST_KEY_PATH,
    MANAGED_KEYS_PATH,
    compute_ssh_fingerprint,
    configure_sshd_authorized_keys_d,
    ensure_host_key,
    register_key_with_server,
    sync_authorized_keys,
)

logger = structlog.get_logger(__name__)


@click.group()
def keys():
    """SSH key lifecycle management."""
    pass


@keys.command()
def init():
    """Initialize host SSH key and register with server.

    Generates ed25519 keypair if missing and registers public key.
    Idempotent - safe to run multiple times.
    """

    async def _init():
        # Load config to get host_id and server URL
        config = load_config()
        if not config.host_id:
            click.echo("Error: Agent not enrolled. Run 'rp register' first.", err=True)
            sys.exit(1)

        # Ensure key exists
        pubkey_path, fingerprint = await ensure_host_key()
        pubkey = pubkey_path.read_text().strip()

        click.echo(f"Host key: {HOST_KEY_PATH}")
        click.echo(f"Fingerprint: {fingerprint}")

        # Register with server
        async with RPClient(base_url=config.server_url) as client:
            try:
                result = await register_key_with_server(
                    client=client,
                    host_id=uuid.UUID(config.host_id),
                    pubkey=pubkey,
                    fingerprint=fingerprint,
                    user_name="root",
                )
                click.echo("\n✓ Key registered with server")
                click.echo(f"  Key ID: {result['id']}")
                click.echo(f"  Created: {result['created_at']}")
            except Exception as e:
                if "already registered" in str(e).lower():
                    click.echo("\n✓ Key already registered (idempotent)")
                else:
                    click.echo(f"\nError: {e}", err=True)
                    sys.exit(1)

    asyncio.run(_init())


@keys.command()
def status():
    """Show local key status and server registration."""

    async def _status():
        config = load_config()

        # Check local key
        if not HOST_KEY_PATH.exists():
            click.echo("Status: No host key generated")
            click.echo("Run 'rp keys init' to generate and register")
            sys.exit(1)

        pubkey_path = HOST_KEY_PATH.with_suffix(".pub")
        pubkey = pubkey_path.read_text().strip()
        fingerprint = compute_ssh_fingerprint(pubkey)

        click.echo("Local Key:")
        click.echo(f"  Path: {HOST_KEY_PATH}")
        click.echo(f"  Fingerprint: {fingerprint}")
        click.echo(f"  Algorithm: {pubkey.split()[0]}")

        if not config.host_id:
            click.echo("\nServer Status: Not enrolled")
            return

        # Check server status
        async with RPClient(base_url=config.server_url) as client:
            try:
                response = await client.get(f"/v1/keys?host_id={config.host_id}")
                response.raise_for_status()
                keys = response.json()

                matching = [k for k in keys if k["fingerprint"] == fingerprint]
                if matching:
                    key = matching[0]
                    click.echo("\nServer Status:")
                    click.echo("  Registered: Yes")
                    click.echo(f"  Key ID: {key['id']}")
                    click.echo(f"  Created: {key['created_at']}")
                    if key.get("revoked_at"):
                        click.echo(f"  REVOKED: {key['revoked_at']}")
                        click.echo(f"  Reason: {key.get('revoked_reason', 'N/A')}")
                else:
                    click.echo("\nServer Status: Not registered")
                    click.echo("Run 'rp keys init' to register")
            except Exception as e:
                click.echo(f"\nServer Status: Error - {e}", err=True)

    asyncio.run(_status())


@keys.command()
def sync():
    """Synchronize authorized_keys from server.

    Fetches authorized keys for this host's group and updates
    /etc/rp/authorized_keys.d/managed if changed.
    """

    async def _sync():
        config = load_config()
        if not config.host_id:
            click.echo("Error: Agent not enrolled", err=True)
            sys.exit(1)

        async with RPClient(base_url=config.server_url) as client:
            try:
                changed = await sync_authorized_keys(client, uuid.UUID(config.host_id))
                if changed:
                    click.echo(f"✓ Authorized keys updated: {MANAGED_KEYS_PATH}")
                else:
                    click.echo("✓ Authorized keys unchanged (idempotent)")
            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)

    asyncio.run(_sync())


@keys.command()
@click.option("--reason", required=True, help="Reason for rotation")
def rotate(reason: str):
    """Rotate host SSH key.

    Generates new keypair, registers with server, revokes old key,
    and syncs authorized_keys.
    """

    async def _rotate():
        config = load_config()
        if not config.host_id:
            click.echo("Error: Agent not enrolled", err=True)
            sys.exit(1)

        # Get old fingerprint
        old_fingerprint = None
        if HOST_KEY_PATH.exists():
            pubkey_path = HOST_KEY_PATH.with_suffix(".pub")
            old_pubkey = pubkey_path.read_text().strip()
            old_fingerprint = compute_ssh_fingerprint(old_pubkey)

        # Remove old key files
        if HOST_KEY_PATH.exists():
            HOST_KEY_PATH.unlink()
        if HOST_KEY_PATH.with_suffix(".pub").exists():
            HOST_KEY_PATH.with_suffix(".pub").unlink()

        # Generate new key
        pubkey_path, new_fingerprint = await ensure_host_key()
        pubkey = pubkey_path.read_text().strip()

        async with RPClient(base_url=config.server_url) as client:
            # Register new key
            try:
                await register_key_with_server(
                    client=client,
                    host_id=uuid.UUID(config.host_id),
                    pubkey=pubkey,
                    fingerprint=new_fingerprint,
                )
                click.echo(f"✓ New key registered: {new_fingerprint}")
            except Exception as e:
                click.echo(f"Error registering new key: {e}", err=True)
                sys.exit(1)

            # Revoke old key
            if old_fingerprint:
                try:
                    response = await client.delete(
                        f"/v1/keys/{old_fingerprint}",
                        params={"reason": reason},
                    )
                    response.raise_for_status()
                    click.echo(f"✓ Old key revoked: {old_fingerprint}")
                except Exception as e:
                    click.echo(f"Warning: Failed to revoke old key: {e}", err=True)

            # Sync authorized_keys
            try:
                await sync_authorized_keys(client, uuid.UUID(config.host_id))
                click.echo("✓ Authorized keys synced")
            except Exception as e:
                click.echo(f"Warning: Failed to sync keys: {e}", err=True)

    asyncio.run(_rotate())


@keys.command("configure-sshd")
def configure_sshd():
    """Configure sshd to read managed authorized_keys.

    Requires sudo. Backs up existing sshd_config and adds:
        AuthorizedKeysFile .ssh/authorized_keys /etc/rp/authorized_keys.d/managed

    Idempotent - safe to run multiple times.
    """

    async def _configure():
        try:
            changed = await configure_sshd_authorized_keys_d()
            if changed:
                click.echo("✓ sshd configured and reloaded")
                click.echo("  Backup: /etc/ssh/sshd_config.rp-backup")
            else:
                click.echo("✓ sshd already configured (idempotent)")
        except PermissionError:
            click.echo("Error: This command requires sudo/root privileges", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    asyncio.run(_configure())
