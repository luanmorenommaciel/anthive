"""anthive monitor — Rich live dashboard for the session fleet.

Public API:
    render_fleet_dashboard(sessions_dir, lf_client, *, only) -> Panel
    watch(sessions_dir, lf_client, *, only, budget_alert, refresh, console) -> None
    snapshot(sessions_dir, lf_client, *, only, console) -> None
    check_budget_alert(sessions_dir, lf_client, threshold) -> list[tuple[str, float]]

Design rules:
- render_fleet_dashboard is a pure function (no side effects).
- lf_client is duck-typed: needs only get_session_metrics(session_id) -> dict.
- All functions tolerate an empty or missing sessions_dir gracefully.
- MERGED sessions are skipped from active rows; counted in the footer.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .schemas import SessionLogFrontmatter, parse_session_log

__all__ = [
    "render_fleet_dashboard",
    "watch",
    "snapshot",
    "check_budget_alert",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State → colour mapping
# ---------------------------------------------------------------------------

_STATE_STYLE: dict[str, str] = {
    "INIT": "yellow",
    "COOKING": "green",
    "CHECKPOINT": "cyan",
    "READY-TO-MERGE": "bold green",
    "BLOCKED": "bold red",
    "MERGED": "dim",
}


def _state_cell(status: str) -> Any:
    """Return a Rich renderable for the given session status."""
    if status == "COOKING":
        return Spinner("dots", text=" COOKING", style="green")
    style = _STATE_STYLE.get(status, "")
    label = status
    return Text(label, style=style)


# ---------------------------------------------------------------------------
# Core renderer
# ---------------------------------------------------------------------------


def _load_sessions(
    sessions_dir: Path,
    only: list[str] | None,
) -> tuple[list[SessionLogFrontmatter], int]:
    """Walk sessions_dir and return (active_sessions, merged_count).

    Active means status != MERGED. _template.md is always skipped.
    If only is provided, filter by substring match against session_id.
    """
    if not sessions_dir.exists():
        return [], 0

    active: list[SessionLogFrontmatter] = []
    merged_count = 0

    for p in sorted(sessions_dir.glob("*.md")):
        if p.name == "_template.md":
            continue
        try:
            fm = parse_session_log(p)
        except Exception as exc:  # noqa: BLE001
            logger.warning("monitor: could not parse %s: %s", p, exc)
            continue

        if only:
            if not any(filt in fm.session_id for filt in only):
                continue

        if fm.status == "MERGED":
            merged_count += 1
            continue

        active.append(fm)

    return active, merged_count


def render_fleet_dashboard(
    sessions_dir: Path,
    lf_client: Any,
    *,
    only: list[str] | None = None,
) -> Panel:
    """Build a Rich Panel showing all active sessions with live Langfuse metrics."""
    active_sessions, merged_count = _load_sessions(sessions_dir, only)

    table = Table(
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("ID", style="cyan", no_wrap=True, min_width=20)
    table.add_column("Task", min_width=12)
    table.add_column("Model", style="dim", min_width=8)
    table.add_column("State", justify="center", min_width=16)
    table.add_column("Tokens", justify="right", min_width=8)
    table.add_column("Cost", justify="right", min_width=8)
    table.add_column("Duration", justify="right", min_width=8)
    table.add_column("Last note", style="dim")

    total_cost = 0.0

    for fm in active_sessions:
        try:
            metrics = lf_client.get_session_metrics(fm.session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "monitor: get_session_metrics failed for %s: %s",
                fm.session_id,
                exc,
            )
            metrics = {
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "duration_s": 0.0,
                "trace_id": None,
                "url": None,
            }

        cost_usd: float = metrics.get("cost_usd", 0.0) or 0.0
        total_cost += cost_usd

        tokens_in: int = metrics.get("tokens_in", 0) or 0
        tokens_out: int = metrics.get("tokens_out", 0) or 0
        total_tokens = tokens_in + tokens_out

        duration_s: float = metrics.get("duration_s", 0.0) or 0.0
        duration_str = f"{duration_s / 60:.1f}m" if duration_s else "-"

        tokens_str = f"{total_tokens:,}" if total_tokens else "-"
        cost_str = f"${cost_usd:.4f}" if cost_usd else "-"

        task_label = (fm.task_id or "")[:30]
        model_label = (fm.model or "")[:12]
        note_label = (fm.last_note or "")[:50]

        table.add_row(
            fm.session_id,
            task_label,
            model_label,
            _state_cell(fm.status),
            tokens_str,
            cost_str,
            duration_str,
            note_label,
        )

    n_active = len(active_sessions)
    footer_parts = [f"{n_active} active"]
    if merged_count:
        footer_parts.append(f"{merged_count} merged")
    footer_parts.append(f"total spend ${total_cost:.4f}")
    footer_line = Text(" · ".join(footer_parts), style="dim")

    from rich.console import Group as RichGroup

    body = RichGroup(table, footer_line)

    timestamp = datetime.now().strftime("%H:%M:%S")
    return Panel(
        body,
        title=f"[bold cyan]anthive[/] [dim]{timestamp}[/]",
        border_style="cyan",
    )


# ---------------------------------------------------------------------------
# watch() — live loop
# ---------------------------------------------------------------------------


def watch(
    sessions_dir: Path,
    lf_client: Any,
    *,
    only: list[str] | None = None,
    budget_alert: float | None = None,
    refresh: float = 3.0,
    console: Console | None = None,
) -> None:
    """Run the live dashboard until KeyboardInterrupt."""
    out = console or Console()

    panel = render_fleet_dashboard(sessions_dir, lf_client, only=only)
    with Live(panel, console=out, refresh_per_second=1, screen=True) as live:
        try:
            while True:
                time.sleep(refresh)
                panel = render_fleet_dashboard(sessions_dir, lf_client, only=only)
                live.update(panel)

                if budget_alert is not None:
                    over_budget = check_budget_alert(sessions_dir, lf_client, budget_alert)
                    for sid, cost in over_budget:
                        logger.warning(
                            "Budget alert: session %s has spent $%.4f (threshold $%.2f)",
                            sid,
                            cost,
                            budget_alert,
                        )
                        print("\a", end="", flush=True)  # terminal bell
        except KeyboardInterrupt:
            pass


# ---------------------------------------------------------------------------
# snapshot() — one-shot render
# ---------------------------------------------------------------------------


def snapshot(
    sessions_dir: Path,
    lf_client: Any,
    *,
    only: list[str] | None = None,
    console: Console | None = None,
) -> None:
    """Render the fleet dashboard once and exit."""
    out = console or Console()
    panel = render_fleet_dashboard(sessions_dir, lf_client, only=only)
    out.print(panel)


# ---------------------------------------------------------------------------
# check_budget_alert()
# ---------------------------------------------------------------------------


def check_budget_alert(
    sessions_dir: Path,
    lf_client: Any,
    threshold: float,
) -> list[tuple[str, float]]:
    """Return (session_id, cost) for any session whose live cost exceeds threshold."""
    active_sessions, _ = _load_sessions(sessions_dir, only=None)
    over_budget: list[tuple[str, float]] = []

    for fm in active_sessions:
        try:
            metrics = lf_client.get_session_metrics(fm.session_id)
        except Exception:  # noqa: BLE001
            continue

        cost_usd: float = metrics.get("cost_usd", 0.0) or 0.0
        if cost_usd > threshold:
            over_budget.append((fm.session_id, cost_usd))

    return over_budget
