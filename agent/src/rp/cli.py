"""Main CLI entry point for Remote-Pulse agent."""

import click
import structlog

from rp import __version__
from rp.commands.install import install
from rp.commands.register import register
from rp.commands.heartbeat import heartbeat
from rp.commands.status import status
from rp.commands.version import version
from rp.commands.uninstall import uninstall

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


@click.group()
@click.version_option(version=__version__, prog_name="rp")
def main():
    """
    Remote-Pulse Agent CLI.

    Universal connectivity, health monitoring, and remote control agent.
    """
    pass


# Register commands
main.add_command(install)
main.add_command(register)
main.add_command(heartbeat)
main.add_command(status)
main.add_command(version)
main.add_command(uninstall)


if __name__ == "__main__":
    main()
