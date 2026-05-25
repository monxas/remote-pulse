"""Register command - re-register with server."""

import click


@click.command()
def register():
    """
    Re-register agent with server.

    F2+ feature: Re-authenticate and update registration.
    Not implemented in F1.
    """
    click.echo("Error: Re-registration not implemented yet (F2 feature)", err=True)
    click.echo("Use 'rp uninstall' then 'rp install' to re-register.", err=True)
    raise click.Abort()
