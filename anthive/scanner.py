"""anthive scanner — discover and classify tasks from a repo's tasks/ directory.

This is a pure module with no CLI dependencies. It reads task markdown files,
in-progress session logs, and the merge queue to produce a ReadyList.

Public API:
    scan(repo_root, tasks_dir, sessions_dir, merge_queue) -> ReadyList
    parse_backlog_blocks(path) -> list[TaskFrontmatter]
"""

from __future__ import annotations

import itertools
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from .schemas import (
    BlockedEntry,
    Conflict,
    DoneEntry,
    InProgressEntry,
    MergeQueueRow,
    ReadyList,
    ReadyListEntry,
    SessionLogFrontmatter,
    TaskFrontmatter,
    parse_merge_queue,
    parse_session_log,
    parse_task_doc,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip-list helpers
# ---------------------------------------------------------------------------

# Files we never treat as task documents — no frontmatter, just navigation docs.
_SKIP_NAMES: frozenset[str] = frozenset({"README.md", "PLAN.md"})


def _should_skip(path: Path) -> bool:
    """Return True when this path should be excluded from task discovery."""
    if path.name.startswith("_"):
        return True
    if path.name.endswith(".example.md"):
        return True
    if path.name in _SKIP_NAMES:
        return True
    # Skip any path component containing "archive"
    if any("archive" in part.lower() for part in path.parts):
        return True
    return False


# ---------------------------------------------------------------------------
# Backlog parser
# ---------------------------------------------------------------------------

# A section header for a backlog sub-task looks like: ### B-some-id
_BACKLOG_HEADER_RE = re.compile(r"^###\s+(B-\S+)", re.MULTILINE)
# Simple key: value lines inside a backlog sub-task section
_KV_RE = re.compile(r"^([a-zA-Z_]+)\s*:\s*(.+)$")


def parse_backlog_blocks(path: Path) -> list[TaskFrontmatter]:
    """Parse a backlog.md file and extract TaskFrontmatter from ### B-* sections.

    Each section between two ### headers (or between a header and EOF) is
    examined for key: value metadata lines. Sections that cannot be parsed
    into a valid TaskFrontmatter are skipped with a warning.
    """
    text = path.read_text(encoding="utf-8")
    results: list[TaskFrontmatter] = []

    # Find all ### B-* header positions
    headers = list(_BACKLOG_HEADER_RE.finditer(text))
    if not headers:
        return results

    for i, match in enumerate(headers):
        block_id = match.group(1)
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[start:end]

        # Gather key: value pairs from the section text
        data: dict[str, object] = {"id": block_id}
        for line in section.splitlines():
            line = line.strip()
            kv = _KV_RE.match(line)
            if kv:
                key, value = kv.group(1).lower(), kv.group(2).strip()
                # Parse list fields
                if key in {"depends_on", "touches_paths", "tags"}:
                    # Accept both "[a, b]" and "a, b" formats
                    cleaned = value.strip("[]")
                    data[key] = [v.strip() for v in cleaned.split(",") if v.strip()]
                else:
                    data[key] = value

        # Apply sane defaults so the Pydantic model can validate
        data.setdefault("title", block_id)
        data.setdefault("status", "ready")
        data.setdefault("effort", "S")
        data.setdefault("budget_usd", 0)
        data.setdefault("agent", "python-developer")
        data.setdefault("depends_on", [])
        data.setdefault("touches_paths", [])

        try:
            fm = TaskFrontmatter.model_validate(data)
            results.append(fm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping backlog block %r in %s: %s", block_id, path, exc)

    return results


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _detect_cycles(tasks: dict[str, TaskFrontmatter]) -> set[str]:
    """Return IDs of tasks that are part of a dependency cycle.

    Uses iterative DFS with three-colour marking (white/grey/black).
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {tid: WHITE for tid in tasks}
    cycle_ids: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        colour[node] = GREY
        path.append(node)
        for dep in tasks[node].depends_on:
            if dep not in tasks:
                continue
            if colour[dep] == GREY:
                # Found a cycle — mark all nodes currently on path
                cycle_start = path.index(dep)
                for n in path[cycle_start:]:
                    cycle_ids.add(n)
            elif colour[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        colour[node] = BLACK

    for tid in list(tasks):
        if colour[tid] == WHITE:
            dfs(tid, [])

    return cycle_ids


def _unresolved_deps(task: TaskFrontmatter, done_ids: set[str]) -> list[str]:
    """Return dep IDs that are not yet in done_ids."""
    return [dep for dep in task.depends_on if dep not in done_ids]


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def _detect_conflicts(entries: list[ReadyListEntry]) -> list[Conflict]:
    """Find pairs of ready tasks that touch overlapping file paths."""
    conflicts: list[Conflict] = []
    for a, b in itertools.combinations(entries, 2):
        intersection = set(a.touches_paths) & set(b.touches_paths)
        if intersection:
            first_path = sorted(intersection)[0]
            conflicts.append(
                Conflict(
                    task_ids=[a.id, b.id],
                    paths=sorted(intersection),
                    note=f"both touch {first_path} — serialize",
                )
            )
    return conflicts


# ---------------------------------------------------------------------------
# Entry builders
# ---------------------------------------------------------------------------


def _make_ready_entry(task: TaskFrontmatter, path: Path, repo_root: Path) -> ReadyListEntry:
    rel = str(path.relative_to(repo_root))
    return ReadyListEntry(
        id=task.id,
        path=rel,
        title=task.title,
        effort=task.effort,
        budget_usd=task.budget_usd,
        agent=task.agent,
        touches_paths=task.touches_paths,
        prefer_model=task.prefer_model,
    )


def _make_blocked_entry(
    task: TaskFrontmatter,
    path: Path,
    repo_root: Path,
    unresolved: list[str],
    explicit_reason: str | None = None,
) -> BlockedEntry:
    rel = str(path.relative_to(repo_root))
    if explicit_reason:
        reason = explicit_reason
    elif unresolved:
        reason = "depends on: " + ", ".join(unresolved)
    else:
        reason = "status: blocked"
    return BlockedEntry(
        id=task.id,
        path=rel,
        blocked_by=unresolved,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# In-progress detection
# ---------------------------------------------------------------------------


def _collect_in_progress(
    sessions_path: Path,
) -> tuple[set[str], list[InProgressEntry], dict[str, SessionLogFrontmatter]]:
    """Walk sessions_dir, return (in_progress_task_ids, entries, session_by_id)."""
    in_progress_ids: set[str] = set()
    entries: list[InProgressEntry] = []
    session_by_id: dict[str, SessionLogFrontmatter] = {}

    if not sessions_path.exists():
        return in_progress_ids, entries, session_by_id

    for log_path in sessions_path.glob("*.md"):
        if log_path.name == "_template.md":
            continue
        try:
            log = parse_session_log(log_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping session log %s: %s", log_path, exc)
            continue

        session_by_id[log.session_id] = log

        if log.status not in {"MERGED"}:
            if log.task_id:
                in_progress_ids.add(log.task_id)
            entries.append(
                InProgressEntry(
                    id=log.task_id or log.session_id,
                    session_id=log.session_id,
                    started=log.created,
                )
            )

    return in_progress_ids, entries, session_by_id


# ---------------------------------------------------------------------------
# Done detection
# ---------------------------------------------------------------------------


def _collect_done(
    merge_queue_path: Path,
    session_by_id: dict[str, SessionLogFrontmatter],
    tasks: dict[str, TaskFrontmatter],
) -> tuple[set[str], list[DoneEntry]]:
    """Build done_ids and DoneEntry list from merge-queue + task frontmatter."""
    done_ids: set[str] = set()
    entries: list[DoneEntry] = []
    seen_ids: set[str] = set()  # avoid duplicates

    # --- From merge-queue rows
    rows: list[MergeQueueRow] = []
    if merge_queue_path.exists():
        try:
            rows = parse_merge_queue(merge_queue_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not parse merge queue %s: %s", merge_queue_path, exc)

    for row in rows:
        if not row.merged:
            continue

        # Map session_name → task_id via session logs (best-effort)
        task_id: str = row.session_name
        session_log = session_by_id.get(row.session_name)
        if session_log and session_log.task_id:
            task_id = session_log.task_id

        done_ids.add(task_id)
        if task_id not in seen_ids:
            seen_ids.add(task_id)
            merged_at: datetime = (
                session_log.created if session_log else datetime.now(timezone.utc)
            )
            entries.append(DoneEntry(id=task_id, merged_at=merged_at))

    # --- From task frontmatter directly
    for tid, task in tasks.items():
        if task.status == "done" and tid not in seen_ids:
            done_ids.add(tid)
            seen_ids.add(tid)
            merged_at = task.created or datetime.now(timezone.utc)
            entries.append(DoneEntry(id=tid, merged_at=merged_at))

    return done_ids, entries


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def scan(
    repo_root: Path,
    tasks_dir: str | Path = "tasks",
    sessions_dir: str | Path = "logs/sessions",
    merge_queue: str | Path = "logs/merge-queue.md",
) -> ReadyList:
    """Scan tasks/**/*.md, classify by status + dependencies, return a ReadyList.

    Args:
        repo_root:    Absolute path to the repository root.
        tasks_dir:    Relative path (from repo_root) to the tasks directory.
        sessions_dir: Relative path to the session logs directory.
        merge_queue:  Relative path to the merge-queue markdown file.

    Returns:
        A ReadyList with tasks classified as ready, blocked, in_progress, or done.
    """
    tasks_path = repo_root / Path(tasks_dir)
    sessions_path = repo_root / Path(sessions_dir)
    merge_queue_path = repo_root / Path(merge_queue)

    # ------------------------------------------------------------------
    # 1. Discover task docs
    # ------------------------------------------------------------------
    tasks: dict[str, tuple[TaskFrontmatter, Path]] = {}

    if tasks_path.exists():
        for md in sorted(tasks_path.rglob("*.md")):
            if _should_skip(md):
                continue
            try:
                fm = parse_task_doc(md)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping %s (parse error): %s", md, exc)
                continue
            if fm is None:
                logger.debug("Skipping %s (no frontmatter)", md)
                continue
            if fm.id in tasks:
                logger.warning("Duplicate task id %r: %s shadows %s", fm.id, md, tasks[fm.id][1])
            tasks[fm.id] = (fm, md)

    # 2. Backlog sub-tasks
    backlog_path = tasks_path / "backlog.md"
    if backlog_path.exists():
        for sub in parse_backlog_blocks(backlog_path):
            if sub.id in tasks:
                logger.debug("Backlog block %r already defined by a task file; skipping", sub.id)
                continue
            tasks[sub.id] = (sub, backlog_path)

    # 3. In-progress from session logs
    in_progress_ids, in_progress_entries, session_by_id = _collect_in_progress(sessions_path)

    # 4. Done from merge-queue + frontmatter
    task_frontmatters = {tid: fm for tid, (fm, _) in tasks.items()}
    done_ids, done_entries = _collect_done(merge_queue_path, session_by_id, task_frontmatters)

    # 5. Cycle detection — warn and add to a "cycle" set
    cycle_ids = _detect_cycles(task_frontmatters)
    if cycle_ids:
        logger.warning("Dependency cycles detected involving: %s", ", ".join(sorted(cycle_ids)))

    # 6. Classify
    ready_entries: list[ReadyListEntry] = []
    blocked_entries: list[BlockedEntry] = []

    for tid, (task, path) in tasks.items():
        # Already classified as done or in_progress
        if tid in done_ids or task.status == "done":
            # Will appear in done_entries; skip here
            continue
        if tid in in_progress_ids or task.status == "in_progress":
            # Will appear in in_progress_entries; skip here
            continue

        # Cycle → blocked
        if tid in cycle_ids:
            blocked_entries.append(
                _make_blocked_entry(task, path, repo_root, [], "dependency cycle")
            )
            continue

        # Explicit blocked status
        if task.status == "blocked":
            unresolved = _unresolved_deps(task, done_ids)
            blocked_entries.append(_make_blocked_entry(task, path, repo_root, unresolved))
            continue

        # Check unresolved dependencies
        unresolved = _unresolved_deps(task, done_ids)
        if unresolved:
            blocked_entries.append(_make_blocked_entry(task, path, repo_root, unresolved))
            continue

        # Eligible for ready
        ready_entries.append(_make_ready_entry(task, path, repo_root))

    # 7. Conflict detection among ready tasks
    conflicts = _detect_conflicts(ready_entries)

    return ReadyList(
        scanned_at=datetime.now(timezone.utc),
        repo_root=str(repo_root.resolve()),
        tasks_dir=str(tasks_dir),
        ready=ready_entries,
        blocked=blocked_entries,
        in_progress=in_progress_entries,
        done=done_entries,
        conflicts=conflicts,
    )
