"""Local policy management commands."""

import os
import sys
import json
import click
import structlog

from rp.local_policy import (
    LocalPolicy,
    CommandDecision,
    touch_flag,
    remove_flag,
    add_to_whitelist,
    remove_from_whitelist,
    show_whitelist,
    get_flag_status,
)

logger = structlog.get_logger()


def _is_root() -> bool:
    """Check if running as root."""
    return os.geteuid() == 0 if hasattr(os, "geteuid") else True


def _require_root() -> None:
    """Exit if not running as root."""
    if not _is_root():
        click.secho(
            "Error: This operation requires root privileges.",
            fg="red",
            err=True,
        )
        click.echo("Run with sudo: sudo rp local ...", err=True)
        sys.exit(1)


def _format_status_line(label: str, value: str, ok: bool = True) -> str:
    """Format a status line with color."""
    if sys.stdout.isatty():
        symbol = "✓" if ok else "✗"
        color = "green" if ok else "red"
        return f"  {click.style(symbol, fg=color)} {label}: {value}"
    else:
        symbol = "[OK]" if ok else "[FAIL]"
        return f"  {symbol} {label}: {value}"


@click.group()
def local():
    """
    Manage local policy enforcement (defense-in-depth).

    Local-approval flags and whitelists provide additional security layer
    beyond server authentication. See ADR-0008 review C3.
    """
    pass


@local.command()
@click.option(
    "--group",
    default="default",
    help="Group to show status for (default/family/prod/iarq)",
)
def status(group: str):
    """Show current local-approval policy status."""
    click.echo(f"Local Policy Status (group: {group})")
    click.echo("=" * 60)

    policy = LocalPolicy()

    # Flags
    click.echo("\nFlags:")
    exec_status = get_flag_status("allow-remote-exec")
    if exec_status["exists"]:
        expired = exec_status["expired"]
        age_hrs = exec_status["age_hours"]
        value = (
            f"ACTIVE ({age_hrs:.1f}h old)"
            if not expired
            else f"EXPIRED ({age_hrs:.1f}h old)"
        )
        click.echo(_format_status_line("allow-remote-exec", value, not expired))
    else:
        click.echo(_format_status_line("allow-remote-exec", "NOT SET", False))

    write_status = get_flag_status("allow-remote-write")
    if write_status["exists"]:
        expired = write_status["expired"]
        age_hrs = write_status["age_hours"]
        value = (
            f"ACTIVE ({age_hrs:.1f}h old)"
            if not expired
            else f"EXPIRED ({age_hrs:.1f}h old)"
        )
        click.echo(_format_status_line("allow-remote-write", value, not expired))
    else:
        click.echo(_format_status_line("allow-remote-write", "NOT SET", False))

    # Whitelists
    click.echo("\nWhitelists:")
    restart_items = show_whitelist("restart-whitelist")
    if restart_items:
        click.echo(
            _format_status_line(
                "restart-whitelist", f"{len(restart_items)} services", True
            )
        )
        for item in restart_items[:5]:
            click.echo(f"      - {item}")
        if len(restart_items) > 5:
            click.echo(f"      ... and {len(restart_items) - 5} more")
    else:
        click.echo(_format_status_line("restart-whitelist", "EMPTY", False))

    read_items = show_whitelist("read-allowlist")
    if read_items:
        click.echo(
            _format_status_line("read-allowlist", f"{len(read_items)} patterns", True)
        )
        for item in read_items[:5]:
            click.echo(f"      - {item}")
        if len(read_items) > 5:
            click.echo(f"      ... and {len(read_items) - 5} more")
    else:
        click.echo(_format_status_line("read-allowlist", "EMPTY", False))

    # Policy directory
    click.echo(f"\nPolicy directory: {policy.policy_dir}")

    is_sensitive = group in ("prod", "iarq")
    click.echo(f"Group tier: {'SENSITIVE' if is_sensitive else 'NON-SENSITIVE'}")


@local.command(name="allow-exec")
@click.option("--ttl", default="24h", help="TTL duration (e.g., 24h, 12h)")
def allow_exec(ttl: str):
    """Enable remote exec_shell commands (requires sudo)."""
    _require_root()

    # Parse TTL (simple format: Xh)
    try:
        if ttl.endswith("h"):
            ttl_hours = int(ttl[:-1])
        else:
            click.secho(
                f"Invalid TTL format: {ttl} (use format: 24h)", fg="red", err=True
            )
            sys.exit(1)
    except ValueError:
        click.secho(f"Invalid TTL format: {ttl}", fg="red", err=True)
        sys.exit(1)

    touch_flag("allow-remote-exec", ttl_hours=ttl_hours)

    if sys.stdout.isatty():
        click.secho("✓", fg="green", nl=False)
        click.echo(f" Remote exec enabled (TTL: {ttl})")
    else:
        click.echo(f"Remote exec enabled (TTL: {ttl})")

    click.echo(f"  Flag expires in {ttl_hours} hours from now.")
    click.echo("  Disable with: sudo rp local deny-exec")


@local.command(name="deny-exec")
def deny_exec():
    """Disable remote exec_shell commands (requires sudo)."""
    _require_root()

    removed = remove_flag("allow-remote-exec")

    if removed:
        if sys.stdout.isatty():
            click.secho("✓", fg="green", nl=False)
            click.echo(" Remote exec disabled")
        else:
            click.echo("Remote exec disabled")
    else:
        click.echo("Remote exec was already disabled")


@local.command(name="approve-write")
@click.option("--ttl", default="24h", help="TTL duration (e.g., 5m, 1h, 24h)")
@click.option("--path", help="Specific path restriction (not yet implemented)")
def approve_write(ttl: str, path: str):
    """Enable remote file_write commands (requires sudo)."""
    _require_root()

    if path:
        click.echo("Warning: --path filtering not yet implemented (ignoring)")

    # Parse TTL
    try:
        if ttl.endswith("h"):
            ttl_hours = int(ttl[:-1])
        elif ttl.endswith("m"):
            ttl_hours = int(ttl[:-1]) / 60.0
        else:
            click.secho(f"Invalid TTL format: {ttl} (use: 24h, 5m)", fg="red", err=True)
            sys.exit(1)
    except ValueError:
        click.secho(f"Invalid TTL format: {ttl}", fg="red", err=True)
        sys.exit(1)

    touch_flag("allow-remote-write", ttl_hours=int(ttl_hours) if ttl_hours >= 1 else 1)

    if sys.stdout.isatty():
        click.secho("✓", fg="green", nl=False)
        click.echo(f" Remote write enabled (TTL: {ttl})")
    else:
        click.echo(f"Remote write enabled (TTL: {ttl})")

    click.echo(
        "  Note: Paths outside /etc/rp/ and /opt/rp/ still require Telegram approval"
    )


@local.group(name="whitelist")
def whitelist():
    """Manage service/path whitelists."""
    pass


@whitelist.command(name="add")
@click.argument("type", type=click.Choice(["restart", "read"]))
@click.argument("item")
def whitelist_add(type: str, item: str):
    """Add item to whitelist (requires sudo)."""
    _require_root()

    whitelist_name = f"{type}-{'whitelist' if type == 'restart' else 'allowlist'}"
    add_to_whitelist(whitelist_name, item)

    if sys.stdout.isatty():
        click.secho("✓", fg="green", nl=False)
        click.echo(f" Added '{item}' to {whitelist_name}")
    else:
        click.echo(f"Added '{item}' to {whitelist_name}")


@whitelist.command(name="rm")
@click.argument("type", type=click.Choice(["restart", "read"]))
@click.argument("item")
def whitelist_rm(type: str, item: str):
    """Remove item from whitelist (requires sudo)."""
    _require_root()

    whitelist_name = f"{type}-{'whitelist' if type == 'restart' else 'allowlist'}"
    removed = remove_from_whitelist(whitelist_name, item)

    if removed:
        if sys.stdout.isatty():
            click.secho("✓", fg="green", nl=False)
            click.echo(f" Removed '{item}' from {whitelist_name}")
        else:
            click.echo(f"Removed '{item}' from {whitelist_name}")
    else:
        click.echo(f"Item '{item}' not found in {whitelist_name}")


@whitelist.command(name="show")
@click.argument("type", type=click.Choice(["restart", "read"]))
def whitelist_show(type: str):
    """Show whitelist contents."""
    whitelist_name = f"{type}-{'whitelist' if type == 'restart' else 'allowlist'}"
    items = show_whitelist(whitelist_name)

    click.echo(f"{whitelist_name}:")
    if items:
        for item in items:
            click.echo(f"  - {item}")
    else:
        click.echo("  (empty)")


@local.command()
@click.argument("command_type")
@click.option("--payload", default="{}", help="Command payload as JSON")
@click.option("--group", default="default", help="Host group")
def evaluate(command_type: str, payload: str, group: str):
    """Dry-run: evaluate command without executing."""
    try:
        payload_dict = json.loads(payload)
    except json.JSONDecodeError as e:
        click.secho(f"Invalid JSON payload: {e}", fg="red", err=True)
        sys.exit(1)

    policy = LocalPolicy()
    decision, reason = policy.evaluate(command_type, payload_dict, group)

    click.echo(f"Command: {command_type}")
    click.echo(f"Group: {group}")
    click.echo(f"Payload: {json.dumps(payload_dict, indent=2)}")
    click.echo()

    if decision == CommandDecision.ALLOW:
        if sys.stdout.isatty():
            click.secho("Decision: ALLOW ✓", fg="green")
        else:
            click.echo("Decision: ALLOW")
    elif decision == CommandDecision.DENY:
        if sys.stdout.isatty():
            click.secho("Decision: DENY ✗", fg="red")
        else:
            click.echo("Decision: DENY")
    else:  # REQUIRE_APPROVAL
        if sys.stdout.isatty():
            click.secho("Decision: REQUIRE_APPROVAL ⏳", fg="yellow")
        else:
            click.echo("Decision: REQUIRE_APPROVAL")

    click.echo(f"Reason: {reason}")
