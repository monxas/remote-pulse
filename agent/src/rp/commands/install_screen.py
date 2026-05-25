"""`rp install-screen` command group (F6-1 + F6-2).

Installs and configures screen-sharing tools (RustDesk, Sunshine, VNC) on
the local host, then reports updated capabilities to the server so they show
up in ``rp screen`` and the dashboard.

Top-level grouping uses ``install-screen`` (dash separator) to avoid colliding
with the existing F1 ``rp install`` command (agent enrollment).
"""

from __future__ import annotations

import asyncio
from typing import Optional

import click
import structlog

from rp.client import RPClient
from rp.config import config_exists, load_config
from rp.installers import (
    InstallResult,
    InstallerError,
    RustDeskInstaller,
    SunshineInstaller,
    VNCInstaller,
)
from rp.platform_detect import detect_screen_capabilities, get_os

logger = structlog.get_logger(__name__)


@click.group(name="install-screen")
def install_screen():
    """Install screen-sharing tools (RustDesk, Sunshine, VNC).

    These are companions to ``rp screen <host>`` (F6-3): the host runs the
    server side (RustDesk Direct IP, Sunshine, or TigerVNC), the local
    machine runs the matching client.
    """


# --------------------------------------------------------------------------
# rustdesk
# --------------------------------------------------------------------------


@install_screen.command("rustdesk")
@click.option("--force", is_flag=True, help="Reinstall even if already present.")
@click.option(
    "--password",
    default=None,
    help="Custom RustDesk password (defaults to 32-char random).",
)
@click.option(
    "--tailscale-ip",
    default=None,
    help="Bind to a specific Tailscale IPv4 (default: detect/0.0.0.0).",
)
@click.option(
    "--skip-server-report",
    is_flag=True,
    help="Don't POST capabilities back to the server.",
)
def install_rustdesk_cmd(
    force: bool,
    password: Optional[str],
    tailscale_ip: Optional[str],
    skip_server_report: bool,
):
    """Install RustDesk client + configure Direct IP mode."""
    asyncio.run(
        _install_rustdesk_async(
            force=force,
            password=password,
            tailscale_ip=tailscale_ip,
            skip_server_report=skip_server_report,
        )
    )


async def _install_rustdesk_async(
    *,
    force: bool,
    password: Optional[str],
    tailscale_ip: Optional[str],
    skip_server_report: bool,
) -> None:
    installer = RustDeskInstaller()
    try:
        result = await installer.install(force=force)
        _render_install_result(result)

        click.echo("Configuring Direct IP mode...")
        cfg = await installer.configure_direct_ip(
            password=password, tailscale_ip=tailscale_ip
        )
        click.secho(
            f"  Direct IP configured, password saved to {cfg['config_path']}",
            fg="green",
        )
        click.echo(f"  bind={cfg['direct_ip']}  id_server={cfg['id_server']}")

        if not skip_server_report:
            await _report_capabilities()
    except InstallerError as exc:
        raise click.ClickException(str(exc))


# --------------------------------------------------------------------------
# sunshine
# --------------------------------------------------------------------------


@install_screen.command("sunshine")
@click.option("--force", is_flag=True, help="Reinstall / override GPU check.")
@click.option(
    "--tailscale-ip",
    default=None,
    help="Bind admin UI to specific Tailscale IPv4.",
)
@click.option(
    "--skip-server-report",
    is_flag=True,
    help="Don't POST capabilities back to the server.",
)
def install_sunshine_cmd(
    force: bool,
    tailscale_ip: Optional[str],
    skip_server_report: bool,
):
    """Install Sunshine GameStream server (Windows GPU hosts only)."""
    if get_os() != "windows":
        raise click.ClickException(
            "Sunshine install is only supported on Windows hosts. "
            "Use `rp install-screen rustdesk` for Linux/macOS."
        )

    asyncio.run(
        _install_sunshine_async(
            force=force,
            tailscale_ip=tailscale_ip,
            skip_server_report=skip_server_report,
        )
    )


async def _install_sunshine_async(
    *,
    force: bool,
    tailscale_ip: Optional[str],
    skip_server_report: bool,
) -> None:
    installer = SunshineInstaller()
    try:
        result = await installer.install(force=force, allow_no_gpu=force)
        _render_install_result(result)

        click.echo("Configuring Sunshine admin UI + firewall...")
        cfg = await installer.configure(tailscale_ip=tailscale_ip)
        click.secho(
            "  Admin URL: " + str(cfg["admin_url"]),
            fg="green",
        )
        click.echo(f"  Username: {cfg['username']}")
        click.echo(f"  Credentials saved to {cfg['config_path']}")
        click.secho(
            "  One-time pairing required: open the admin URL in a browser to "
            "pair Moonlight client.",
            fg="yellow",
        )

        if not skip_server_report:
            await _report_capabilities()
    except InstallerError as exc:
        raise click.ClickException(str(exc))


# --------------------------------------------------------------------------
# vnc
# --------------------------------------------------------------------------


@install_screen.command("vnc")
@click.option("--force", is_flag=True, help="Reinstall even if present.")
@click.option(
    "--tailscale-ip",
    default=None,
    help="Bind VNC to specific Tailscale IPv4.",
)
@click.option("--port", default=5901, show_default=True, help="VNC port.")
@click.option(
    "--skip-server-report",
    is_flag=True,
    help="Don't POST capabilities back to the server.",
)
def install_vnc_cmd(
    force: bool,
    tailscale_ip: Optional[str],
    port: int,
    skip_server_report: bool,
):
    """Install TigerVNC server (Linux GUI fallback)."""
    if get_os() != "linux":
        raise click.ClickException("VNC install is only supported on Linux hosts.")

    asyncio.run(
        _install_vnc_async(
            force=force,
            tailscale_ip=tailscale_ip,
            port=port,
            skip_server_report=skip_server_report,
        )
    )


async def _install_vnc_async(
    *,
    force: bool,
    tailscale_ip: Optional[str],
    port: int,
    skip_server_report: bool,
) -> None:
    installer = VNCInstaller()
    try:
        result = await installer.install(force=force)
        _render_install_result(result)

        click.echo("Configuring VNC...")
        cfg = await installer.configure(tailscale_ip=tailscale_ip, port=port)
        click.secho(
            f"  VNC bound to {cfg['bind_addr']}:{cfg['port']}, password "
            f"saved to {cfg['config_path']}",
            fg="green",
        )

        if not skip_server_report:
            await _report_capabilities()
    except InstallerError as exc:
        raise click.ClickException(str(exc))


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


@install_screen.command("status")
def install_status_cmd():
    """Show which screen-sharing tools are installed locally."""
    asyncio.run(_status_async())


async def _status_async() -> None:
    rustdesk = RustDeskInstaller()
    sunshine = SunshineInstaller()
    vnc = VNCInstaller()

    rd_installed = await rustdesk.detect_installed()
    rd_version = await rustdesk.detect_version() if rd_installed else None

    sun_installed = await sunshine.detect_installed()
    sun_version = await sunshine.detect_version() if sun_installed else None

    vnc_installed = await vnc.detect_installed()

    rows = [
        ("RustDesk", rd_installed, rd_version or "—"),
        ("Sunshine", sun_installed, sun_version or "—"),
        ("TigerVNC", vnc_installed, "—"),
    ]

    click.echo("Screen-sharing tools (local host):")
    click.echo(f"  {'Tool':<10} {'Installed':<12} {'Version'}")
    click.echo("  " + "-" * 36)
    for tool, installed, version in rows:
        symbol = (
            click.style("✓", fg="green") if installed else click.style("✗", fg="red")
        )
        flag = "yes" if installed else "no"
        click.echo(f"  {tool:<10} {symbol} {flag:<10} {version}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _render_install_result(result: InstallResult) -> None:
    """Print a one-line summary of an install step."""
    if result.skipped:
        click.secho(
            f"= {result.tool} already installed "
            f"({result.version or 'version unknown'}); skipping. "
            "Re-run with --force to reinstall.",
            fg="yellow",
        )
        return
    version = result.version or "unknown"
    method = result.method or "?"
    click.secho(
        f"+ {result.tool} {version} installed via {method}",
        fg="green",
    )


async def _report_capabilities() -> None:
    """POST current screen capabilities to the server (best-effort)."""
    if not config_exists():
        click.secho(
            "  Skipping server report: agent not enrolled (run `rp install` first).",
            fg="yellow",
        )
        return

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as exc:
        click.secho(f"  Skipping server report: {exc}", fg="yellow")
        return

    caps = detect_screen_capabilities()
    try:
        async with RPClient(config) as client:
            resp = await client.update_capabilities(caps)
    except Exception as exc:  # noqa: BLE001 — server breakage shouldn't fail install
        logger.warning("report_capabilities_failed", error=str(exc))
        click.secho(f"  Skipping server report: {exc}", fg="yellow")
        return

    if resp.get("status") == "warning":
        click.secho(f"  {resp.get('message', 'Server endpoint warning.')}", fg="yellow")
    else:
        click.secho("  Reported capabilities to server.", fg="green")
