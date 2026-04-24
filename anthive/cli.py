"""anthive CLI — typer entry point.

This is a stub. The full CLI is assembled in p1-p7 per tasks/PLAN.md.

Subcommands (implemented incrementally):
    scan      → p1
    compose   → p2
    dispatch  → p3 (local) / p6 (cloud)
    watch     → p4
    status    → p4
    merge     → p5
    capture   → p7
    init      → post-M1
"""

import typer
from rich.console import Console

from . import __version__

app = typer.Typer(
    name="anthive",
    help="A structured swarm for Claude Code — parallel autonomous sessions.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


@app.callback()
def main_callback() -> None:
    """anthive — a structured swarm for Claude Code."""


@app.command()
def version() -> None:
    """Show anthive version."""
    console.print(f"anthive [bold cyan]{__version__}[/]")


# TODO(p1): register `scan` subcommand
# TODO(p2): register `compose` subcommand
# TODO(p3): register `dispatch` subcommand (local)
# TODO(p4): register `watch` and `status` subcommands
# TODO(p5): register `merge` subcommand
# TODO(p6): extend `dispatch` with --cloud
# TODO(p7): register `capture` subcommand


if __name__ == "__main__":
    app()
