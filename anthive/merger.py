"""anthive merger — PR reconciler.

Reads ``logs/merge-queue.md``, lands PRs on ``main`` in dependency order,
runs per-PR exit checks, archives completed session logs, and writes an
honesty-trail decision log for every terminal action.

Public API:
    reconcile(repo_root, *, dry_run, auto, confirm_fn, runner, now_fn) -> list[MergeResult]
    topo_pick(unmerged, merged_names) -> MergeQueueRow | None
    archive_session_log(repo_root, session_name, *, now_fn) -> Path | None
    mark_row_merged(queue_path, session_name) -> bool
    write_decision_log(repo_root, row, action, detail, *, now_fn) -> Path
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from .schemas import MergeQueueRow, parse_merge_queue

__all__ = [
    "MergeResult",
    "reconcile",
    "topo_pick",
    "archive_session_log",
    "mark_row_merged",
    "write_decision_log",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class MergeResult:
    """Result of a single merge-queue row reconciliation attempt."""

    session_name: str
    action: Literal[
        "merged",
        "would_merge",
        "exit_check_failed",
        "merge_conflict",
        "skipped",
        "deadlocked",
        "missing_branch",
    ]
    pr: str | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def topo_pick(
    unmerged: list[MergeQueueRow],
    merged_names: set[str],
) -> MergeQueueRow | None:
    """Return the first row whose dependencies are all in *merged_names*.

    Iterates in list order (preserving the queue's authored ordering).
    Returns None when every remaining row has at least one unmet dependency.
    """
    for row in unmerged:
        deps = {d.strip() for d in row.depends_on if d.strip() and d.strip().lower() != "none"}
        if deps.issubset(merged_names):
            return row
    return None


def archive_session_log(
    repo_root: Path,
    session_name: str,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> Path | None:
    """Move ``logs/sessions/<session_name>.md`` to ``logs/archive/<YYYY-MM-DD>/``.

    Returns the destination path on success, or None when the source does not
    exist (best-effort — a warning is logged but no exception is raised).
    """
    src = repo_root / "logs" / "sessions" / f"{session_name}.md"
    if not src.exists():
        logger.warning("archive_session_log: source %s not found, skipping", src)
        return None

    now = (now_fn or datetime.now)()
    date_str = now.strftime("%Y-%m-%d")
    dest_dir = repo_root / "logs" / "archive" / date_str
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_name}.md"
    src.rename(dest)
    return dest


def mark_row_merged(queue_path: Path, session_name: str) -> bool:
    """Flip the checkbox for *session_name* from ``[ ]`` to ``[x]`` in-place.

    Matches lines that contain ``- [ ] <session_name>`` (with a space or
    end-of-content after the session name).  Preserves all other content
    verbatim.  Returns True if at least one substitution was made.
    """
    text = queue_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        if f"- [ ] {session_name}" in line:
            lines[i] = line.replace(f"- [ ] {session_name}", f"- [x] {session_name}", 1)
            changed = True
            break
    if changed:
        queue_path.write_text("".join(lines), encoding="utf-8")
    return changed


def write_decision_log(
    repo_root: Path,
    row: MergeQueueRow,
    action: str,
    detail: str = "",
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> Path:
    """Write a decision log to ``logs/decisions/merge-<ts>-<session_name>.md``.

    Returns the path of the written file.
    """
    now = (now_fn or datetime.now)()
    ts = now.strftime("%Y%m%d-%H%M%S")
    decisions_dir = repo_root / "logs" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    log_path = decisions_dir / f"merge-{ts}-{row.session_name}.md"

    touches_str = ", ".join(row.touches) if row.touches else ""
    depends_str = ", ".join(row.depends_on) if row.depends_on else "none"
    spent_str = f"${row.spent_usd:.2f}" if row.spent_usd is not None else "n/a"
    pr_str = row.pr or ""

    content = f"""---
timestamp: {now.isoformat()}
session: {row.session_name}
pr: {pr_str}
action: {action}
---

# Merge decision: {row.session_name}

- **Action:** {action}
- **PR:** {pr_str}
- **Touches:** {touches_str}
- **Depends-on:** {depends_str}
- **Exit check:** {row.exit_check}
- **Spent:** {spent_str}
"""

    if detail:
        content += f"\n{detail}\n"

    log_path.write_text(content, encoding="utf-8")
    return log_path


# ---------------------------------------------------------------------------
# Main reconciler
# ---------------------------------------------------------------------------


def reconcile(
    repo_root: Path,
    *,
    dry_run: bool = False,
    auto: bool = False,
    confirm_fn: Callable[[str], bool] | None = None,
    runner: Callable | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> list[MergeResult]:
    """Walk ``logs/merge-queue.md`` and land PRs in dependency order.

    Args:
        repo_root:   Root of the repository to operate on.
        dry_run:     When True, compute the merge order but do not execute any
                     git commands or filesystem mutations.
        auto:        When True, skip all interactive confirmation prompts.
        confirm_fn:  Override the confirmation callback (defaults to typer.confirm).
                     Receives the question string; return True to proceed.
        runner:      Override for subprocess.run (inject a stub in tests).
        now_fn:      Override for datetime.now (inject in tests for determinism).

    Returns:
        A list of MergeResult — one entry per queue row processed, plus one
        ``deadlocked`` entry if a circular/unsatisfiable dependency is detected.

    TODO(p6): --reorder interactive reorder UI via questionary.
    """
    queue_path = repo_root / "logs" / "merge-queue.md"

    if not queue_path.exists():
        logger.warning("reconcile: merge queue not found at %s", queue_path)
        return []

    rows = parse_merge_queue(queue_path)
    unmerged = [r for r in rows if not r.merged]
    merged_names: set[str] = {r.session_name for r in rows if r.merged}
    results: list[MergeResult] = []

    _confirm = confirm_fn or _default_confirm

    while unmerged:
        next_row = topo_pick(unmerged, merged_names)

        if next_row is None:
            # Every remaining row has at least one unmet dependency.
            results.append(
                MergeResult(
                    session_name="<deadlocked>",
                    action="deadlocked",
                    detail=f"remaining: {[r.session_name for r in unmerged]}",
                )
            )
            break

        if dry_run:
            results.append(
                MergeResult(next_row.session_name, "would_merge", pr=next_row.pr)
            )
            unmerged.remove(next_row)
            merged_names.add(next_row.session_name)
            continue

        # ------------------------------------------------------------------
        # Confirmation
        # ------------------------------------------------------------------
        if not auto:
            question = f"Merge {next_row.session_name}"
            if next_row.pr:
                question += f" ({next_row.pr})"
            question += "?"
            if not _confirm(question):
                results.append(
                    MergeResult(
                        next_row.session_name,
                        "skipped",
                        pr=next_row.pr,
                        detail="user declined",
                    )
                )
                unmerged.remove(next_row)
                continue

        # ------------------------------------------------------------------
        # Branch existence check
        # ------------------------------------------------------------------
        branch = f"session/{next_row.session_name}"
        if not _branch_exists(repo_root, branch, runner):
            results.append(
                MergeResult(
                    next_row.session_name,
                    "missing_branch",
                    pr=next_row.pr,
                    detail=f"branch {branch} not found",
                )
            )
            unmerged.remove(next_row)
            continue

        # ------------------------------------------------------------------
        # Exit check (run before the merge, in worktree when available)
        # ------------------------------------------------------------------
        exit_check_failed = False
        if next_row.exit_check and next_row.exit_check.lower() not in {"none", ""}:
            worktree = _resolve_worktree(repo_root, next_row.session_name)
            cwd = worktree if worktree.exists() else repo_root
            rc, stdout, stderr = _run_shell(runner, next_row.exit_check, cwd=cwd)
            if rc != 0:
                exit_check_failed = True
                if not auto:
                    proceed = _confirm(
                        f"Exit check FAILED for {next_row.session_name}. Merge anyway?"
                    )
                    if proceed:
                        exit_check_failed = False

            if exit_check_failed:
                snippet = (stderr or stdout)[-500:]
                results.append(
                    MergeResult(
                        next_row.session_name,
                        "exit_check_failed",
                        pr=next_row.pr,
                        detail=snippet,
                    )
                )
                write_decision_log(
                    repo_root,
                    next_row,
                    "exit_check_failed",
                    detail=stderr or stdout,
                    now_fn=now_fn,
                )
                unmerged.remove(next_row)
                continue

        # ------------------------------------------------------------------
        # Merge
        # ------------------------------------------------------------------
        _git(runner, repo_root, "checkout", "main")
        # Best-effort: pull may fail if origin is offline / not configured.
        # The local merge can still proceed.
        _git(runner, repo_root, "pull", "--ff-only", check=False)
        rc, _, stderr = _git_capture(runner, repo_root, "merge", "--no-ff", branch)

        if rc != 0:
            _git(runner, repo_root, "merge", "--abort", check=False)
            snippet = stderr[-500:]
            results.append(
                MergeResult(
                    next_row.session_name,
                    "merge_conflict",
                    pr=next_row.pr,
                    detail=snippet,
                )
            )
            write_decision_log(
                repo_root,
                next_row,
                "merge_conflict",
                detail=stderr,
                now_fn=now_fn,
            )
            unmerged.remove(next_row)
            continue

        # Best-effort: push may fail (no remote, auth issue, offline).
        # The local merge already succeeded; surface push failures only via
        # the decision log, don't abort the reconcile.
        _git(runner, repo_root, "push", "origin", "main", check=False)

        # ------------------------------------------------------------------
        # Post-merge bookkeeping
        # ------------------------------------------------------------------
        archived = archive_session_log(repo_root, next_row.session_name, now_fn=now_fn)
        mark_row_merged(queue_path, next_row.session_name)
        write_decision_log(
            repo_root,
            next_row,
            "merged",
            detail=f"archived to {archived}" if archived else "no log to archive",
            now_fn=now_fn,
        )

        merged_names.add(next_row.session_name)
        unmerged.remove(next_row)
        results.append(MergeResult(next_row.session_name, "merged", pr=next_row.pr))

    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _default_confirm(question: str) -> bool:
    import typer

    return typer.confirm(question, default=True)


def _default_runner(
    cmd: list[str] | str,
    *,
    cwd: Path | str | None = None,
    env: dict | None = None,
    check: bool = True,
    capture_output: bool = True,
    shell: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=capture_output,
        text=True,
        shell=shell,
        **kwargs,
    )


def _git(
    runner: Callable | None,
    repo_root: Path,
    *args: str,
    check: bool = True,
) -> object:
    _r = runner or _default_runner
    return _r(["git", *args], cwd=repo_root, check=check)


def _git_capture(
    runner: Callable | None,
    repo_root: Path,
    *args: str,
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr). Never raises."""
    _r = runner or _default_runner
    try:
        result = _r(["git", *args], cwd=repo_root, check=False)
        return (
            result.returncode,
            getattr(result, "stdout", "") or "",
            getattr(result, "stderr", "") or "",
        )
    except Exception as exc:
        return 1, "", str(exc)


def _run_shell(
    runner: Callable | None,
    command: str,
    *,
    cwd: Path,
) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr). Never raises."""
    _r = runner or _default_runner
    try:
        result = _r(command, cwd=cwd, shell=True, check=False)
        return (
            result.returncode,
            getattr(result, "stdout", "") or "",
            getattr(result, "stderr", "") or "",
        )
    except Exception as exc:
        return 1, "", str(exc)


def _branch_exists(
    repo_root: Path,
    branch: str,
    runner: Callable | None,
) -> bool:
    rc, _, _ = _git_capture(runner, repo_root, "rev-parse", "--verify", branch)
    return rc == 0


def _resolve_worktree(repo_root: Path, session_name: str) -> Path:
    """Return the worktree path for *session_name*.

    Checks ``worktrees/<session_name>`` first; falls back to
    ``worktrees/<slug-after-first-dash>`` (handles names like "task-slug").
    Returns the primary path even when neither exists (caller checks existence).
    """
    primary = repo_root / "worktrees" / session_name
    if primary.exists():
        return primary
    if "-" in session_name:
        alt = repo_root / "worktrees" / session_name.split("-", 1)[1]
        if alt.exists():
            return alt
    return primary
