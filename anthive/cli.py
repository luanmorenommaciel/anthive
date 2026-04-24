"""anthive CLI — typer entry point.

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

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from . import __version__

__all__ = ["app"]

app = typer.Typer(
    name="anthive",
    help="A structured swarm for Claude Code — parallel autonomous sessions.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Default console (may be replaced per-command when --plain/NO_COLOR is set)
console = Console()


def _make_console(*, plain: bool) -> Console:
    """Build a Rich Console that respects --plain and NO_COLOR."""
    no_color = plain or bool(os.environ.get("NO_COLOR", ""))
    if no_color:
        return Console(no_color=True, force_terminal=False, highlight=False)
    return Console()


@app.callback()
def main_callback() -> None:
    """anthive — a structured swarm for Claude Code."""


@app.command()
def version() -> None:
    """Show anthive version."""
    console.print(f"anthive [bold cyan]{__version__}[/]")


# ---------------------------------------------------------------------------
# p1 — scan subcommand
# ---------------------------------------------------------------------------


@app.command()
def scan(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
    plain: bool = typer.Option(False, "--plain", help="No ANSI/colors (CI-friendly)."),
    watch: bool = typer.Option(False, "--watch", help="Re-scan every 2s; press Ctrl-C to exit."),
    repo_root: Path = typer.Option(Path.cwd(), "--repo", help="Repo root to scan (default: cwd)."),
) -> None:
    """Scan tasks/ and show what's ready to work on."""
    from .scanner import scan as do_scan

    out = _make_console(plain=plain)

    def _run_once() -> None:
        try:
            result = do_scan(repo_root)
        except Exception as exc:  # noqa: BLE001
            out.print(f"[red]Error scanning {repo_root}: {exc}[/]", file=sys.stderr)
            raise typer.Exit(code=2) from exc

        if json_out:
            typer.echo(result.model_dump_json(indent=2))
            return

        _render_table(out, result)

    if watch:
        try:
            while True:
                out.clear()
                _run_once()
                time.sleep(2)
        except KeyboardInterrupt:
            pass
    else:
        _run_once()


def _render_table(out: Console, result: object) -> None:
    """Render the ReadyList as a Rich table."""
    from rich.table import Table

    # Import here to keep scanner.py import-light
    from .schemas import ReadyList

    assert isinstance(result, ReadyList)

    n_ready = len(result.ready)
    n_blocked = len(result.blocked)
    n_in_progress = len(result.in_progress)
    n_done = len(result.done)

    table = Table(
        title=(
            f"anthive scan — {n_ready} ready / {n_blocked} blocked"
            f" / {n_in_progress} in-progress / {n_done} done"
        ),
        show_header=True,
        header_style="bold",
    )
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status", justify="center")
    table.add_column("Effort", justify="center")
    table.add_column("Budget", justify="right")
    table.add_column("Agent")

    for r in result.ready:
        budget = f"${r.budget_usd:.0f}" if r.budget_usd else "-"
        table.add_row(r.id, r.title, "[green]READY[/]", r.effort, budget, r.agent)

    for ip in result.in_progress:
        table.add_row(ip.id, "", "[cyan]IN-PROGRESS[/]", "-", "-", ip.session_id)

    for b in result.blocked:
        table.add_row(b.id, b.reason, "[yellow]BLOCKED[/]", "-", "-", "-")

    for d in result.done:
        table.add_row(d.id, "", "[dim]DONE[/]", "-", "-", "-")

    out.print(table)

    if result.conflicts:
        out.print("\n[bold red]Path conflicts detected:[/]")
        for c in result.conflicts:
            ids = " + ".join(c.task_ids)
            out.print(f"  {ids}")
            for p in c.paths:
                out.print(f"    [yellow]·[/] {p}")


# TODO(p2): register `compose` subcommand
# TODO(p3): register `dispatch` subcommand (local)
# TODO(p4): register `watch` and `status` subcommands
# TODO(p5): register `merge` subcommand
# TODO(p6): extend `dispatch` with --cloud
# TODO(p7): register `capture` subcommand


if __name__ == "__main__":
    app()
