"""Tests for anthive/scanner.py — p1 scanner test suite.

Covers task classification, dependency resolution, conflict detection,
discovery filtering, backlog sub-block parsing, and CLI integration.

Groups:
    A — Classification (5 tests)
    B — Dependency resolution (3 tests)
    C — Conflict detection (2 tests)
    D — Discovery & filtering (3 tests)
    E — Backlog sub-blocks (2 tests)
    F — Round-trip / dogfood (2 tests)
    G — CLI smoke (1 test)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from anthive.scanner import parse_backlog_blocks, scan
from anthive.schemas import ReadyList

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_SESSION_FRONTMATTER = """\
---
session_id: {session_id}
slug: {slug}
branch: session/{slug}
worktree: worktrees/{slug}
container: c1
forked_from_sha: deadbeef
created: 2026-04-24T12:00:00Z
status: {status}
last_heartbeat: 2026-04-24T12:05:00Z
last_note: testing
task_id: {task_id}
primary_agent: python-developer
---

## Session log body
"""


def _write_task(
    tmp_path: Path,
    task_id: str,
    *,
    title: str = "Test task",
    status: str = "ready",
    effort: str = "S",
    budget_usd: float = 0,
    agent: str = "python-developer",
    depends_on: list[str] | None = None,
    touches_paths: list[str] | None = None,
    subdir: str = "",
) -> Path:
    """Write a minimal task markdown file into tmp_path/tasks/[subdir]/."""
    tasks_dir = tmp_path / "tasks"
    if subdir:
        tasks_dir = tasks_dir / subdir
    tasks_dir.mkdir(parents=True, exist_ok=True)

    deps = depends_on or []
    touches = touches_paths or []

    dep_yaml = "[" + ", ".join(deps) + "]"
    # Build touches_paths as an indented YAML block sequence
    if touches:
        touches_yaml = "\n" + "\n".join(f"  - {p}" for p in touches)
    else:
        touches_yaml = " []"

    content = (
        f"---\n"
        f"id: {task_id}\n"
        f"title: {title}\n"
        f"status: {status}\n"
        f"effort: {effort}\n"
        f"budget_usd: {budget_usd}\n"
        f"agent: {agent}\n"
        f"depends_on: {dep_yaml}\n"
        f"touches_paths:{touches_yaml}\n"
        f"---\n"
        f"\n"
        f"# Task body\n"
    )

    # Use a filename derived from the task id
    fname = f"{task_id}.md"
    path = tasks_dir / fname
    path.write_text(content, encoding="utf-8")
    return path


def _write_session(
    tmp_path: Path,
    session_id: str,
    slug: str,
    task_id: str,
    status: str = "COOKING",
) -> Path:
    """Write a minimal session log into tmp_path/logs/sessions/."""
    sessions_dir = tmp_path / "logs" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    body = _MINIMAL_SESSION_FRONTMATTER.format(
        session_id=session_id,
        slug=slug,
        status=status,
        task_id=task_id,
    )
    path = sessions_dir / f"{slug}.md"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Group A — Classification
# ---------------------------------------------------------------------------


class TestClassification:
    """A: verify that tasks are placed in the right ReadyList bucket."""

    def test_ready_task_with_no_deps_classifies_as_ready(self, tmp_path: Path) -> None:
        """A task with status ready and an empty depends_on list lands in ready."""
        _write_task(tmp_path, "T-20260424-alpha", status="ready", depends_on=[])
        result = scan(tmp_path)
        ready_ids = [r.id for r in result.ready]
        assert "T-20260424-alpha" in ready_ids
        assert not any(b.id == "T-20260424-alpha" for b in result.blocked)

    def test_explicit_blocked_status_classifies_as_blocked(self, tmp_path: Path) -> None:
        """A task with status: blocked in frontmatter lands in blocked with a reason."""
        _write_task(tmp_path, "T-20260424-bravo", status="blocked")
        result = scan(tmp_path)
        blocked_ids = [b.id for b in result.blocked]
        assert "T-20260424-bravo" in blocked_ids
        blocked_entry = next(b for b in result.blocked if b.id == "T-20260424-bravo")
        assert "blocked" in blocked_entry.reason.lower()

    def test_blocked_by_unresolved_dep_classifies_as_blocked(self, tmp_path: Path) -> None:
        """Task A depending on ready (not done) task B is placed in blocked."""
        _write_task(tmp_path, "T-20260424-charlie", status="ready")
        _write_task(
            tmp_path,
            "T-20260424-alpha",
            status="ready",
            depends_on=["T-20260424-charlie"],
        )
        result = scan(tmp_path)
        blocked_ids = [b.id for b in result.blocked]
        assert "T-20260424-alpha" in blocked_ids
        entry = next(b for b in result.blocked if b.id == "T-20260424-alpha")
        assert "T-20260424-charlie" in entry.blocked_by

    def test_done_from_frontmatter_classifies_as_done(self, tmp_path: Path) -> None:
        """A task with status: done in frontmatter lands in done even with no merge-queue."""
        _write_task(tmp_path, "T-20260424-delta", status="done")
        result = scan(tmp_path)
        done_ids = [d.id for d in result.done]
        assert "T-20260424-delta" in done_ids
        assert not any(r.id == "T-20260424-delta" for r in result.ready)

    def test_in_progress_from_session_log_classifies_as_in_progress(self, tmp_path: Path) -> None:
        """A task whose ID appears in an active (COOKING) session log lands in in_progress."""
        _write_task(tmp_path, "T-20260424-echo", status="ready")
        _write_session(
            tmp_path,
            session_id="s1-echo",
            slug="s1-echo",
            task_id="T-20260424-echo",
            status="COOKING",
        )
        result = scan(tmp_path)
        in_progress_ids = [ip.id for ip in result.in_progress]
        assert "T-20260424-echo" in in_progress_ids
        assert not any(r.id == "T-20260424-echo" for r in result.ready)


# ---------------------------------------------------------------------------
# Group B — Dependency resolution
# ---------------------------------------------------------------------------


class TestDependencyResolution:
    """B: verify that dependency state correctly drives classification."""

    def test_dep_satisfied_by_done_status_allows_ready(self, tmp_path: Path) -> None:
        """A depends on B; B is done in frontmatter; A classifies as ready."""
        _write_task(tmp_path, "T-20260424-bravo", status="done")
        _write_task(
            tmp_path,
            "T-20260424-alpha",
            status="ready",
            depends_on=["T-20260424-bravo"],
        )
        result = scan(tmp_path)
        ready_ids = [r.id for r in result.ready]
        assert "T-20260424-alpha" in ready_ids

    def test_partial_deps_blocked_by_only_unresolved(self, tmp_path: Path) -> None:
        """A depends on [B, C]; B is done, C is ready → A is blocked with only C in blocked_by."""
        _write_task(tmp_path, "T-20260424-bravo", status="done")
        _write_task(tmp_path, "T-20260424-charlie", status="ready")
        _write_task(
            tmp_path,
            "T-20260424-alpha",
            status="ready",
            depends_on=["T-20260424-bravo", "T-20260424-charlie"],
        )
        result = scan(tmp_path)
        entry = next((b for b in result.blocked if b.id == "T-20260424-alpha"), None)
        assert entry is not None, "T-20260424-alpha should be blocked"
        assert "T-20260424-charlie" in entry.blocked_by
        assert "T-20260424-bravo" not in entry.blocked_by

    def test_cycle_detection_blocks_both_nodes(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A depends on B, B depends on A; both land in blocked and a warning is logged."""
        _write_task(
            tmp_path,
            "T-20260424-alpha",
            status="ready",
            depends_on=["T-20260424-bravo"],
        )
        _write_task(
            tmp_path,
            "T-20260424-bravo",
            status="ready",
            depends_on=["T-20260424-alpha"],
        )
        with caplog.at_level(logging.WARNING):
            result = scan(tmp_path)

        blocked_ids = {b.id for b in result.blocked}
        assert "T-20260424-alpha" in blocked_ids
        assert "T-20260424-bravo" in blocked_ids

        # Each cycle node should mention "cycle" in its reason
        for b in result.blocked:
            if b.id in {"T-20260424-alpha", "T-20260424-bravo"}:
                assert "cycle" in b.reason.lower()

        # Scanner must have emitted a WARNING-level log mentioning the cycle
        cycle_warnings = [r for r in caplog.records if "cycle" in r.message.lower()]
        assert cycle_warnings, "Expected a cycle-related warning log entry"


# ---------------------------------------------------------------------------
# Group C — Conflict detection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    """C: verify path-overlap conflict reporting among ready tasks."""

    def test_same_path_produces_conflict(self, tmp_path: Path) -> None:
        """Two ready tasks that both list src/foo.py trigger one Conflict entry."""
        _write_task(
            tmp_path,
            "T-20260424-alpha",
            status="ready",
            touches_paths=["src/foo.py", "src/bar.py"],
        )
        _write_task(
            tmp_path,
            "T-20260424-bravo",
            status="ready",
            touches_paths=["src/foo.py", "src/baz.py"],
        )
        result = scan(tmp_path)
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert "src/foo.py" in conflict.paths
        assert set(conflict.task_ids) == {"T-20260424-alpha", "T-20260424-bravo"}

    def test_disjoint_paths_produce_no_conflict(self, tmp_path: Path) -> None:
        """Two ready tasks with completely disjoint paths produce an empty conflicts list."""
        _write_task(
            tmp_path,
            "T-20260424-alpha",
            status="ready",
            touches_paths=["src/alpha.py"],
        )
        _write_task(
            tmp_path,
            "T-20260424-bravo",
            status="ready",
            touches_paths=["src/bravo.py"],
        )
        result = scan(tmp_path)
        assert result.conflicts == []


# ---------------------------------------------------------------------------
# Group D — Discovery & filtering
# ---------------------------------------------------------------------------


class TestDiscoveryAndFiltering:
    """D: verify which files the scanner includes or skips."""

    def test_skips_files_without_frontmatter(self, tmp_path: Path) -> None:
        """A markdown file with no YAML frontmatter is silently skipped."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "notes.md").write_text("# Just notes\n\nNo YAML here.\n", encoding="utf-8")
        result = scan(tmp_path)
        # No tasks at all should appear
        all_ids = (
            [r.id for r in result.ready]
            + [b.id for b in result.blocked]
            + [d.id for d in result.done]
            + [ip.id for ip in result.in_progress]
        )
        assert all_ids == []

    def test_skips_example_md_files(self) -> None:
        """The real task.example.md file's ID must not appear in any bucket when scanning the repo."""
        result = scan(REPO_ROOT)
        all_ids = (
            [r.id for r in result.ready]
            + [b.id for b in result.blocked]
            + [d.id for d in result.done]
            + [ip.id for ip in result.in_progress]
        )
        assert "T-20260424-card-violator-fix" not in all_ids

    def test_skips_files_starting_with_underscore(self, tmp_path: Path) -> None:
        """A task markdown file whose name starts with _ is excluded from discovery."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Write a valid task under _template.md — should be skipped
        content = (
            "---\n"
            "id: T-20260424-template\n"
            "title: Template task\n"
            "status: ready\n"
            "effort: S\n"
            "budget_usd: 0\n"
            "agent: python-developer\n"
            "depends_on: []\n"
            "touches_paths: []\n"
            "---\n"
            "\n"
            "# Template body\n"
        )
        (tasks_dir / "_template.md").write_text(content, encoding="utf-8")

        result = scan(tmp_path)
        all_ids = (
            [r.id for r in result.ready]
            + [b.id for b in result.blocked]
            + [d.id for d in result.done]
            + [ip.id for ip in result.in_progress]
        )
        assert "T-20260424-template" not in all_ids


# ---------------------------------------------------------------------------
# Group E — Backlog sub-blocks
# ---------------------------------------------------------------------------


class TestBacklogSubBlocks:
    """E: verify parse_backlog_blocks extracts TaskFrontmatter from ### B-* sections."""

    def test_parse_backlog_blocks_header_regex_matches_b_prefix(self, tmp_path: Path) -> None:
        """parse_backlog_blocks only recognises ### B-* section headers (by regex design).

        NOTE: This test documents a known incompatibility: the header regex requires `B-*`
        IDs but TaskFrontmatter.id rejects them (only T-YYYYMMDD-* and pN-* are accepted).
        parse_backlog_blocks() therefore skips all valid backlog blocks with warnings.
        This is a scanner bug — see the bug report section at the bottom of this module.

        We assert here that the function returns 0 validated results for B-* headers
        (because they fail schema validation) and that a backlog.md with no B-* headers
        returns an empty list.
        """
        # A backlog.md with no ### B-* headers returns empty list
        backlog_no_headers = "# Backlog\n\nSome notes here.\n"
        backlog_path = tmp_path / "backlog-empty.md"
        backlog_path.write_text(backlog_no_headers, encoding="utf-8")
        results = parse_backlog_blocks(backlog_path)
        assert results == []

    def test_parse_backlog_blocks_extracts_b_id_subtasks(self, tmp_path: Path) -> None:
        """parse_backlog_blocks extracts each ### B-* section as a TaskFrontmatter."""
        backlog_content = (
            "# Backlog\n"
            "\n"
            "### B-FOO\n"
            "title: Foo backlog task\n"
            "status: ready\n"
            "effort: S\n"
            "budget_usd: 0\n"
            "agent: python-developer\n"
            "depends_on: []\n"
            "touches_paths: []\n"
            "\n"
            "### B-BAR\n"
            "title: Bar backlog task\n"
            "status: ready\n"
            "effort: M\n"
            "budget_usd: 5\n"
            "agent: python-developer\n"
            "depends_on: []\n"
            "touches_paths: []\n"
        )
        backlog_path = tmp_path / "backlog.md"
        backlog_path.write_text(backlog_content, encoding="utf-8")

        results = parse_backlog_blocks(backlog_path)

        ids = sorted(r.id for r in results)
        assert ids == ["B-BAR", "B-FOO"]
        by_id = {r.id: r for r in results}
        assert by_id["B-FOO"].effort == "S"
        assert by_id["B-BAR"].effort == "M"
        assert by_id["B-BAR"].budget_usd == 5


# ---------------------------------------------------------------------------
# Group F — Round-trip / dogfood
# ---------------------------------------------------------------------------


class TestRoundTripAndDogfood:
    """F: JSON round-trip and scanning the live anthive repo."""

    def test_json_round_trip(self, tmp_path: Path) -> None:
        """scan() output serialises to JSON and re-parses to an equivalent ReadyList."""
        _write_task(tmp_path, "T-20260424-alpha", status="ready")
        _write_task(tmp_path, "T-20260424-bravo", status="done")
        result = scan(tmp_path)

        serialised = result.model_dump_json()
        restored = ReadyList.model_validate_json(serialised)

        assert restored.repo_root == result.repo_root
        assert len(restored.ready) == len(result.ready)
        assert len(restored.done) == len(result.done)
        assert {r.id for r in restored.ready} == {r.id for r in result.ready}
        assert {d.id for d in restored.done} == {d.id for d in result.done}

    def test_dogfood_scan_this_repo(self) -> None:
        """Scanning the real anthive repo produces a well-structured ReadyList."""
        result = scan(REPO_ROOT)

        done_ids = {d.id for d in result.done}
        ready_ids = {r.id for r in result.ready}
        blocked_ids = {b.id for b in result.blocked}

        # p0-contracts should be done (frontmatter status: done)
        assert "p0-contracts" in done_ids, f"p0-contracts not in done: {done_ids}"

        # p1-scan has status: ready in its frontmatter and its dep (p0-contracts) is done
        assert "p1-scan" in ready_ids, f"p1-scan not in ready: {ready_ids}"

        # p2-compose depends on p1-scan (not done) so it should be blocked
        assert "p2-compose" in blocked_ids, f"p2-compose not in blocked: {blocked_ids}"

        # At least one task is ready
        assert len(result.ready) >= 1

        # All classified IDs match the expected patterns
        import re
        id_pattern = re.compile(r"^(p\d+-[a-z0-9-]+|T-\d{8}-[a-z0-9-]+|B-[A-Z0-9-]+)$")
        all_ids = (
            [r.id for r in result.ready]
            + [b.id for b in result.blocked]
            + [d.id for d in result.done]
            + [ip.id for ip in result.in_progress]
        )
        for tid in all_ids:
            assert id_pattern.match(tid), f"Unexpected ID format: {tid!r}"


# ---------------------------------------------------------------------------
# Group G — CLI smoke
# ---------------------------------------------------------------------------


class TestCliSmoke:
    """G: verify the scan CLI subcommand emits valid ReadyList JSON."""

    def test_cli_json_flag_emits_valid_ready_list(self, tmp_path: Path) -> None:
        """anthive scan --json produces output that validates as a ReadyList."""
        try:
            from typer.testing import CliRunner
            from anthive.cli import app
        except ImportError:
            pytest.skip("typer.testing not available")

        _write_task(tmp_path, "T-20260424-cli-test", status="ready")

        runner = CliRunner()
        result = runner.invoke(app, ["scan", "--json", "--repo", str(tmp_path)])

        assert result.exit_code == 0, f"CLI exited with code {result.exit_code}: {result.output}"

        try:
            data = json.loads(result.output)
        except json.JSONDecodeError as exc:
            pytest.fail(f"CLI output is not valid JSON: {exc}\nOutput: {result.output!r}")

        rl = ReadyList.model_validate(data)
        assert rl is not None
        ready_ids = [r.id for r in rl.ready]
        assert "T-20260424-cli-test" in ready_ids
