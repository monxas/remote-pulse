"""Version command - show agent version."""

import platform
import sys

import click

from rp import __version__
from rp.platform_detect import get_arch, get_os


@click.command()
def version():
    """Show agent version and runtime information."""
    click.echo(f"remote-pulse agent version {__version__}")
    click.echo()
    click.echo("Runtime:")
    click.echo(
        f"  Python:       {sys.version_info.major}.{sys.version_info.minor}"
        f".{sys.version_info.micro}"
    )
    click.echo(f"  Platform:     {get_os()} ({get_arch()})")
    click.echo(f"  Node:         {platform.node()}")
