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
            typer.echo(f"Error scanning {repo_root}: {exc}", err=True)
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


# ---------------------------------------------------------------------------
# p2 — compose subcommand
# ---------------------------------------------------------------------------


@app.command()
def compose(
    task_id: str | None = typer.Argument(None, help="Task ID; omit if --all-ready."),
    all_ready: bool = typer.Option(False, "--all-ready", help="Compose for every ready task."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print to stdout, don't write."),
    repo_root: Path = typer.Option(Path.cwd(), "--repo", help="Repo root."),
) -> None:
    """Generate a deterministic session prompt for one task or every ready task."""
    from .composer import compose as do_compose
    from .scanner import scan as do_scan
    from .schemas import parse_task_doc

    result = do_scan(repo_root)

    # Build (entry, task_path) pairs for all ready entries
    all_ready_entries = list(result.ready)

    if all_ready:
        targets = [(e, repo_root / e.path) for e in all_ready_entries]
    elif task_id:
        matched = [e for e in all_ready_entries if e.id == task_id]
        if not matched:
            typer.echo(
                f"Task {task_id!r} not found in ready set. "
                f"Run `anthive scan` to see what's ready.",
                err=True,
            )
            raise typer.Exit(code=1)
        targets = [(matched[0], repo_root / matched[0].path)]
    else:
        typer.echo("Must specify task_id or --all-ready.", err=True)
        raise typer.Exit(code=2)

    # All ready + in-progress task IDs (for other_active computation)
    # We fetch full TaskFrontmatter for every ready entry so we can pass them
    # as other_active to the composer.
    entry_frontmatters: dict[str, object] = {}
    for entry in all_ready_entries:
        fm = parse_task_doc(repo_root / entry.path)
        if fm is not None:
            entry_frontmatters[entry.id] = fm

    prompts_dir = repo_root / "prompts"

    for entry, task_path in targets:
        fm = parse_task_doc(task_path)
        if fm is None:
            typer.echo(
                f"Could not parse task frontmatter from {task_path}",
                err=True,
            )
            raise typer.Exit(code=1)

        # other_active = all ready tasks except this one
        other_active = [
            v
            for k, v in entry_frontmatters.items()
            if k != fm.id
        ]

        try:
            prompt_text = do_compose(fm, task_path, repo_root, other_active)  # type: ignore[arg-type]
        except ValueError as exc:
            typer.echo(f"Compose failed for {fm.id!r}: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        out_path = prompts_dir / f"{fm.id}.md"

        if dry_run:
            console.print(f"\n[bold]── prompts/{fm.id}.md ──[/]\n")
            console.print(prompt_text)
        else:
            prompts_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(prompt_text, encoding="utf-8")
            console.print(f"[green]✓[/] prompts/{fm.id}.md")


# TODO(p3): register `dispatch` subcommand (local)
# TODO(p4): register `watch` and `status` subcommands
# TODO(p5): register `merge` subcommand
# TODO(p6): extend `dispatch` with --cloud
# TODO(p7): register `capture` subcommand


if __name__ == "__main__":
    app()
