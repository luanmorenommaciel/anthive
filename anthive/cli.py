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
import subprocess
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


# ---------------------------------------------------------------------------
# p3 — dispatch subcommand (local)
# ---------------------------------------------------------------------------


@app.command()
def dispatch(
    task_id: str | None = typer.Argument(None, help="Task ID to dispatch; omit if --all-ready."),
    all_ready: bool = typer.Option(False, "--all-ready", help="Dispatch every ready task."),
    local: bool = typer.Option(True, "--local/--no-local", help="Dispatch locally via tmux (default)."),
    cloud: bool = typer.Option(False, "--cloud", help="Dispatch via Managed Agents (p6 — not yet implemented)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without executing."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
    plain: bool = typer.Option(False, "--plain", help="No ANSI/colors (CI-friendly)."),
    repo_root: Path = typer.Option(Path.cwd(), "--repo", help="Repo root (default: cwd)."),
) -> None:
    """Dispatch task(s) to Claude Code session(s)."""
    from .config import load_config
    from .dispatchers.base import AlreadyDispatchedError, PreflightError
    from .dispatchers.local import LocalDispatcher
    from .scanner import scan as do_scan
    from .schemas import parse_task_doc

    out = _make_console(plain=plain)

    # ------------------------------------------------------------------
    # 1. Guard: cloud not implemented yet
    # ------------------------------------------------------------------
    if cloud:
        typer.echo(
            "Cloud dispatch lands in p6. Re-run with --local or wait for p6.",
            err=True,
        )
        raise typer.Exit(code=2)

    # ------------------------------------------------------------------
    # 2. Load config
    # ------------------------------------------------------------------
    cfg = load_config(repo_root)

    # ------------------------------------------------------------------
    # 3. Scan to find ready tasks
    # ------------------------------------------------------------------
    try:
        result = do_scan(repo_root)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Error scanning {repo_root}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    ready_map = {e.id: e for e in result.ready}

    # ------------------------------------------------------------------
    # 4. Build target list
    # ------------------------------------------------------------------
    if all_ready:
        targets = list(result.ready)
    elif task_id:
        if task_id not in ready_map:
            typer.echo(
                f"Task {task_id!r} not found in the ready set. "
                f"Run `anthive scan` to see what's ready.",
                err=True,
            )
            raise typer.Exit(code=1)
        targets = [ready_map[task_id]]
    else:
        typer.echo(
            "Specify a task_id argument or pass --all-ready.",
            err=True,
        )
        raise typer.Exit(code=2)

    if not targets:
        out.print("[yellow]No ready tasks to dispatch.[/]")
        raise typer.Exit(code=0)

    # ------------------------------------------------------------------
    # 5. Concurrency cap pre-check
    # ------------------------------------------------------------------
    max_concurrent: int = cfg["dispatcher"]["local"].get("max_concurrent_sessions", 4)
    prefix: str = cfg["dispatcher"]["local"].get("tmux_session_prefix", "anthive-")

    # Count existing tmux sessions matching our prefix (best-effort).
    existing_count = _count_tmux_sessions(prefix)

    schedulable = max(0, max_concurrent - existing_count)
    over_cap = len(targets) > schedulable

    if schedulable == 0:
        typer.echo(
            f"Concurrency cap reached ({existing_count}/{max_concurrent} sessions active). "
            f"No new sessions will be dispatched.",
            err=True,
        )
        raise typer.Exit(code=3)

    targets_to_run = targets[:schedulable]
    targets_skipped = targets[schedulable:]

    # ------------------------------------------------------------------
    # 6. Confirmation panel
    # ------------------------------------------------------------------
    from rich.panel import Panel
    from rich.table import Table

    tbl = Table(show_header=True, header_style="bold", box=None)
    tbl.add_column("ID", style="cyan", no_wrap=True)
    tbl.add_column("Title")
    tbl.add_column("Agent")
    tbl.add_column("Budget", justify="right")

    for e in targets_to_run:
        budget = f"${e.budget_usd:.2f}" if e.budget_usd else "-"
        tbl.add_row(e.id, e.title, e.agent, budget)

    mode_label = "DRY RUN — " if dry_run else ""
    out.print(
        Panel(
            tbl,
            title=f"[bold]{mode_label}Dispatch {len(targets_to_run)} task(s) — local[/]",
            expand=False,
        )
    )

    if targets_skipped:
        out.print(
            f"[yellow]Warning:[/] {len(targets_skipped)} task(s) will be skipped "
            f"(concurrency cap {max_concurrent})."
        )

    if not dry_run and not yes:
        confirmed = typer.confirm("Proceed?", default=True)
        if not confirmed:
            raise typer.Abort()

    # ------------------------------------------------------------------
    # 7. Dispatch each target
    # ------------------------------------------------------------------
    local_cfg = cfg["dispatcher"]["local"]
    obs_cfg = cfg.get("observability", {})

    handles = []
    dispatched_ids: list[dict] = []

    for entry in targets_to_run:
        # Resolve full TaskFrontmatter from the task file.
        task_path = repo_root / entry.path
        fm = parse_task_doc(task_path)
        if fm is None:
            typer.echo(f"Could not parse frontmatter from {task_path}; skipping.", err=True)
            continue

        # Resolve prompt: use existing file if present, otherwise compose on the fly.
        from .composer import compose as do_compose, slugify

        prompts_dir = repo_root / cfg["paths"].get("prompts_dir", "prompts/")
        prompt_file = prompts_dir / f"{fm.id}.md"

        if prompt_file.exists():
            prompt_text = prompt_file.read_text(encoding="utf-8")
        else:
            other_active_entries = [
                parse_task_doc(repo_root / e.path)
                for e in result.ready
                if e.id != fm.id
            ]
            other_active = [t for t in other_active_entries if t is not None]
            try:
                prompt_text = do_compose(fm, task_path, repo_root, other_active)
            except ValueError as exc:
                typer.echo(f"Compose failed for {fm.id!r}: {exc}", err=True)
                raise typer.Exit(code=1) from exc

        slug = slugify(fm.id)

        if dry_run:
            worktree_dir = local_cfg.get("worktree_dir", "worktrees/")
            pane = f"{prefix}{slug}"
            out.print(
                f"[yellow]DRY RUN:[/] would dispatch [cyan]{fm.id}[/] "
                f"to worktree [dim]{worktree_dir}{slug}[/], "
                f"tmux [dim]{pane}[/]"
            )
            continue

        dispatcher = LocalDispatcher(local_cfg, obs_cfg)
        try:
            handle = dispatcher.dispatch(fm, prompt_text, repo_root)
        except AlreadyDispatchedError as exc:
            out.print(f"[yellow]Already dispatched:[/] {exc}")
            continue
        except PreflightError as exc:
            typer.echo(f"Pre-flight failed for {fm.id!r}: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        handles.append(handle)
        dispatched_ids.append({
            "session_id": handle.session_id,
            "task_id": handle.task_id,
            "container": handle.container,
            "log_path": str(handle.log_path),
            "branch": handle.branch,
        })

        out.print(
            f"[green]✓[/] [cyan]{handle.session_id}[/] at "
            f"tmux://[bold]{handle.container}[/]"
        )
        out.print(f"  log: [dim]{handle.log_path}[/]")

    # ------------------------------------------------------------------
    # 8. JSON output (if requested)
    # ------------------------------------------------------------------
    if json_out and dispatched_ids:
        import json
        typer.echo(json.dumps(dispatched_ids, indent=2))

    # ------------------------------------------------------------------
    # 9. Exit codes
    # ------------------------------------------------------------------
    if targets_skipped and not dry_run:
        raise typer.Exit(code=3)


def _count_tmux_sessions(prefix: str) -> int:
    """Count running tmux sessions whose name starts with *prefix*.

    Returns 0 if tmux is not installed or no server is running.
    """
    try:
        result = subprocess.run(
            ["tmux", "ls", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return 0
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return sum(1 for n in names if n.startswith(prefix))
    except FileNotFoundError:
        return 0


# ---------------------------------------------------------------------------
# p4 — watch subcommand
# ---------------------------------------------------------------------------


@app.command()
def watch(
    only: str | None = typer.Option(
        None, "--only", help="Comma-separated session IDs (or prefixes) to filter."
    ),
    budget_alert: float | None = typer.Option(
        None, "--budget-alert", help="USD threshold; ring terminal bell if any session exceeds it."
    ),
    plain: bool = typer.Option(False, "--plain", help="No ANSI/colors (CI-friendly)."),
    refresh: float = typer.Option(3.0, "--refresh", help="Seconds between dashboard refreshes."),
    repo_root: Path = typer.Option(Path.cwd(), "--repo", help="Repo root (default: cwd)."),
) -> None:
    """Live dashboard of all sessions with cost/tokens from Langfuse."""
    from .config import load_config
    from .langfuse_client import LangfuseClient
    from .monitor import watch as do_watch
    from .observability import init_tracing

    out = _make_console(plain=plain)
    cfg = load_config(repo_root)

    # Best-effort OTEL init; never crash the CLI.
    try:
        init_tracing(endpoint=cfg["observability"].get("otel_endpoint"))
    except Exception:  # noqa: BLE001
        pass

    lf_client = LangfuseClient(
        base_url=cfg["observability"]["langfuse_url"],
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
    )

    sessions_dir = repo_root / "logs" / "sessions"
    if not sessions_dir.exists():
        out.print(
            "(no sessions yet — dispatch one with [cyan]anthive dispatch <id>[/])"
        )
        raise typer.Exit(code=0)

    only_list = [s.strip() for s in only.split(",")] if only else None

    do_watch(
        sessions_dir,
        lf_client,
        only=only_list,
        budget_alert=budget_alert,
        refresh=refresh,
        console=out,
    )


# ---------------------------------------------------------------------------
# p4 — status subcommand
# ---------------------------------------------------------------------------


@app.command()
def status(
    only: str | None = typer.Option(
        None, "--only", help="Comma-separated session IDs (or prefixes) to filter."
    ),
    plain: bool = typer.Option(False, "--plain", help="No ANSI/colors (CI-friendly)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
    repo_root: Path = typer.Option(Path.cwd(), "--repo", help="Repo root (default: cwd)."),
) -> None:
    """One-shot fleet snapshot. Same data as watch, no live refresh."""
    import json as _json

    from .config import load_config
    from .langfuse_client import LangfuseClient
    from .monitor import snapshot as do_snapshot
    from .observability import init_tracing
    from .schemas import parse_session_log

    out = _make_console(plain=plain)
    cfg = load_config(repo_root)

    # Best-effort OTEL init.
    try:
        init_tracing(endpoint=cfg["observability"].get("otel_endpoint"))
    except Exception:  # noqa: BLE001
        pass

    lf_client = LangfuseClient(
        base_url=cfg["observability"]["langfuse_url"],
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
    )

    sessions_dir = repo_root / "logs" / "sessions"
    if not sessions_dir.exists():
        out.print(
            "(no sessions yet — dispatch one with [cyan]anthive dispatch <id>[/])"
        )
        raise typer.Exit(code=0)

    only_list = [s.strip() for s in only.split(",")] if only else None

    if json_out:
        # Emit JSON object per session with live Langfuse metrics.
        rows: list[dict] = []
        for p in sorted(sessions_dir.glob("*.md")):
            if p.name == "_template.md":
                continue
            try:
                fm = parse_session_log(p)
            except Exception:  # noqa: BLE001
                continue
            if only_list and not any(f in fm.session_id for f in only_list):
                continue
            metrics = lf_client.get_session_metrics(fm.session_id)
            rows.append(
                {
                    "session_id": fm.session_id,
                    "task_id": fm.task_id,
                    "status": fm.status,
                    "model": fm.model,
                    "last_note": fm.last_note,
                    **metrics,
                }
            )
        typer.echo(_json.dumps(rows, indent=2))
        return

    do_snapshot(sessions_dir, lf_client, only=only_list, console=out)


# TODO(p5): register `merge` subcommand
# TODO(p6): extend `dispatch` with --cloud
# TODO(p7): register `capture` subcommand


if __name__ == "__main__":
    app()
