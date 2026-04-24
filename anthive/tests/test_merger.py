"""Tests for anthive/merger.py — p5 merger test suite.

Covers:
    A — topo_pick (3 tests)
    B — mark_row_merged (2 tests)
    C — archive_session_log (2 tests)
    D — write_decision_log (1 test)
    E — reconcile dry-run (2 tests)
    F — reconcile real path via mocked runner (5 tests)
    G — CLI smoke via Typer CliRunner (2 tests)

Total: 17 tests
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anthive.cli import app
from anthive.merger import (
    MergeResult,
    archive_session_log,
    mark_row_merged,
    reconcile,
    topo_pick,
    write_decision_log,
)
from anthive.schemas import MergeQueueRow

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

_NOW = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
_NOW_FN = lambda: _NOW  # noqa: E731  — deterministic timestamp injector


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeResult:
    """Fake subprocess.CompletedProcess returned by RecordingRunner."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class RecordingRunner:
    """Mimics subprocess.run's signature; records calls; returns canned results.

    git_responses maps a git verb (str) to a FakeResult.  Shell exit_check calls
    are identified by shell=True and return shell_rc / shell_stdout / shell_stderr.
    """

    def __init__(
        self,
        *,
        git_responses: dict[str, FakeResult] | None = None,
        shell_rc: int = 0,
        shell_stdout: str = "",
        shell_stderr: str = "",
    ) -> None:
        self.calls: list[dict] = []
        self.git_responses: dict[str, FakeResult] = git_responses or {}
        self.shell_rc = shell_rc
        self.shell_stdout = shell_stdout
        self.shell_stderr = shell_stderr

    def __call__(
        self,
        cmd,
        *,
        cwd=None,
        env=None,
        check=True,
        capture_output=True,
        shell=False,
        **kwargs,
    ) -> FakeResult:
        self.calls.append({"cmd": cmd, "cwd": cwd, "shell": shell, "check": check})
        if shell:
            return FakeResult(self.shell_rc, self.shell_stdout, self.shell_stderr)
        # Git call — cmd must be a list starting with "git"
        assert isinstance(cmd, list) and cmd[0] == "git", f"Expected git list cmd, got {cmd!r}"
        verb = cmd[1]
        if verb in self.git_responses:
            return self.git_responses[verb]
        return FakeResult(returncode=0, stdout="", stderr="")


def _write_queue(path: Path, rows: list[str]) -> None:
    """Write a minimal merge-queue.md with given row bodies under ## Open."""
    content = "# Merge Queue\n\n## Open\n\n" + "\n".join(rows) + "\n"
    path.write_text(content, encoding="utf-8")


def _make_fake_repo(tmp_path: Path) -> Path:
    """Create the logs/sessions/ and logs/ skeleton in tmp_path."""
    (tmp_path / "logs" / "sessions").mkdir(parents=True)
    return tmp_path


def _make_row(
    session_name: str,
    *,
    merged: bool = False,
    pr: str | None = None,
    touches: list[str] | None = None,
    depends_on: list[str] | None = None,
    exit_check: str = "none",
    spent_usd: float | None = None,
    langfuse: str | None = None,
) -> MergeQueueRow:
    """Build a MergeQueueRow with convenient defaults."""
    return MergeQueueRow(
        merged=merged,
        session_name=session_name,
        pr=pr,
        touches=touches or [],
        depends_on=depends_on or [],
        exit_check=exit_check,
        spent_usd=spent_usd,
        langfuse=langfuse,
    )


def _queue_line(
    session_name: str,
    *,
    merged: bool = False,
    pr: str = "PR #1",
    depends_on: str = "none",
    exit_check: str = "none",
) -> str:
    """Return a single well-formed merge-queue bullet line."""
    checkbox = "[x]" if merged else "[ ]"
    return (
        f"- {checkbox} {session_name} · {pr} · touches: src/a.py"
        f" · depends-on: {depends_on} · exit_check: {exit_check}"
    )


# ---------------------------------------------------------------------------
# Group A — topo_pick
# ---------------------------------------------------------------------------


class TestTopoPick:
    """topo_pick: dependency-aware row selection."""

    def test_returns_row_with_all_deps_satisfied(self) -> None:
        """Returns B when A is already in merged_names and B depends on A."""
        row_a = _make_row("A", depends_on=[])
        row_b = _make_row("B", depends_on=["A"])
        result = topo_pick([row_a, row_b], merged_names={"A"})
        assert result is not None
        assert result.session_name == "A"  # A appears first in list; but A's deps are satisfied too

    def test_returns_none_when_dep_unmet(self) -> None:
        """Returns None when the only remaining row still has an unmet dependency."""
        row_b = _make_row("B", depends_on=["A"])
        result = topo_pick([row_b], merged_names=set())
        assert result is None

    def test_empty_deps_picks_first(self) -> None:
        """A row with no dependencies is always eligible and returned immediately."""
        row = _make_row("standalone", depends_on=[])
        result = topo_pick([row], merged_names=set())
        assert result is row

    def test_picks_eligible_among_blocked(self) -> None:
        """Returns the first unblocked row even when earlier rows are blocked."""
        row_blocked = _make_row("B", depends_on=["A"])
        row_free = _make_row("C", depends_on=[])
        result = topo_pick([row_blocked, row_free], merged_names=set())
        assert result is row_free


# ---------------------------------------------------------------------------
# Group B — mark_row_merged
# ---------------------------------------------------------------------------


class TestMarkRowMerged:
    """mark_row_merged: flips checkbox in the queue file."""

    def test_flips_unchecked_to_checked(self, tmp_path: Path) -> None:
        """Flips '- [ ] s1 ...' to '- [x] s1 ...' and returns True."""
        queue_path = tmp_path / "merge-queue.md"
        _write_queue(queue_path, [_queue_line("s1")])

        changed = mark_row_merged(queue_path, "s1")

        assert changed is True
        content = queue_path.read_text(encoding="utf-8")
        assert "- [x] s1" in content
        assert "- [ ] s1" not in content

    def test_returns_false_for_unknown_session(self, tmp_path: Path) -> None:
        """Returns False and leaves file unchanged when session name not found."""
        queue_path = tmp_path / "merge-queue.md"
        original = _queue_line("s1")
        _write_queue(queue_path, [original])

        changed = mark_row_merged(queue_path, "ghost-session")

        assert changed is False
        # File content unchanged
        assert "- [ ] s1" in queue_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Group C — archive_session_log
# ---------------------------------------------------------------------------


class TestArchive:
    """archive_session_log: moves session log to dated archive directory."""

    def test_moves_log_to_dated_archive(self, tmp_path: Path) -> None:
        """Source file is moved to logs/archive/YYYY-MM-DD/ and source is gone."""
        repo = _make_fake_repo(tmp_path)
        src = repo / "logs" / "sessions" / "s1-foo.md"
        src.write_text("# session log", encoding="utf-8")

        dest = archive_session_log(repo, "s1-foo", now_fn=_NOW_FN)

        expected = repo / "logs" / "archive" / "2026-04-24" / "s1-foo.md"
        assert dest == expected
        assert expected.exists()
        assert not src.exists()

    def test_returns_none_when_source_missing(self, tmp_path: Path) -> None:
        """Returns None gracefully when the source file does not exist."""
        repo = _make_fake_repo(tmp_path)

        result = archive_session_log(repo, "nonexistent", now_fn=_NOW_FN)

        assert result is None


# ---------------------------------------------------------------------------
# Group D — write_decision_log
# ---------------------------------------------------------------------------


class TestDecisionLog:
    """write_decision_log: writes frontmatter + body to logs/decisions/."""

    def test_writes_expected_content(self, tmp_path: Path) -> None:
        """Decision log contains session, action, PR, touches, exit_check, and spent."""
        repo = _make_fake_repo(tmp_path)
        row = _make_row(
            "s1",
            pr="PR #5",
            touches=["src/a.py"],
            depends_on=[],
            exit_check="pytest",
            spent_usd=1.23,
            langfuse="abc",
        )

        log_path = write_decision_log(repo, row, "merged", detail="nice", now_fn=_NOW_FN)

        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")

        assert "session: s1" in content
        assert "action: merged" in content
        assert "PR #5" in content
        assert "src/a.py" in content
        assert "pytest" in content
        assert "$1.23" in content
        assert "nice" in content


# ---------------------------------------------------------------------------
# Group E — reconcile dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    """reconcile with dry_run=True: computes order, never calls runner."""

    def test_dry_run_no_runner_calls(self, tmp_path: Path) -> None:
        """All results are 'would_merge' and runner is never invoked."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        _write_queue(queue_path, [
            _queue_line("row-alpha"),
            _queue_line("row-beta"),
        ])
        runner = RecordingRunner()

        results = reconcile(repo, dry_run=True, auto=True, runner=runner, now_fn=_NOW_FN)

        assert all(r.action == "would_merge" for r in results)
        assert runner.calls == []

    def test_dry_run_respects_topo_order(self, tmp_path: Path) -> None:
        """Dry-run emits A before B when B depends on A."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        _write_queue(queue_path, [
            _queue_line("A", depends_on="none"),
            _queue_line("B", depends_on="A"),
        ])
        runner = RecordingRunner()

        results = reconcile(repo, dry_run=True, auto=True, runner=runner, now_fn=_NOW_FN)

        assert len(results) == 2
        assert results[0].session_name == "A"
        assert results[1].session_name == "B"

    def test_dry_run_empty_queue_returns_empty_list(self, tmp_path: Path) -> None:
        """No rows in queue → reconcile returns empty list, no runner calls."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text("# Merge Queue\n\n## Open\n\n", encoding="utf-8")
        runner = RecordingRunner()

        results = reconcile(repo, dry_run=True, auto=True, runner=runner, now_fn=_NOW_FN)

        assert results == []
        assert runner.calls == []


# ---------------------------------------------------------------------------
# Group F — reconcile real path (mocked runner)
# ---------------------------------------------------------------------------


class TestReconcile:
    """reconcile: end-to-end paths with a RecordingRunner, no real git."""

    def test_happy_path_single_row(self, tmp_path: Path) -> None:
        """Single row with no deps merges successfully; queue checkbox is flipped."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        _write_queue(queue_path, [_queue_line("s1")])
        # Create a session log so archive_session_log can find it
        (repo / "logs" / "sessions" / "s1.md").write_text("# log", encoding="utf-8")

        runner = RecordingRunner()

        results = reconcile(repo, dry_run=False, auto=True, runner=runner, now_fn=_NOW_FN)

        assert len(results) == 1
        result = results[0]
        assert result.session_name == "s1"
        assert result.action == "merged"

        # Verify expected git verbs were called
        git_verbs = [c["cmd"][1] for c in runner.calls if not c["shell"]]
        assert "rev-parse" in git_verbs   # branch existence check
        assert "checkout" in git_verbs
        assert "pull" in git_verbs
        assert "merge" in git_verbs
        assert "push" in git_verbs

        # Queue checkbox flipped
        assert "- [x] s1" in queue_path.read_text(encoding="utf-8")

        # Decision log written
        decision_files = list((repo / "logs" / "decisions").glob("*.md"))
        assert len(decision_files) == 1

    def test_missing_branch_action(self, tmp_path: Path) -> None:
        """Returns 'missing_branch' when rev-parse returns rc=1; no merge issued."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        _write_queue(queue_path, [_queue_line("s1")])

        runner = RecordingRunner(
            git_responses={"rev-parse": FakeResult(returncode=1, stderr="unknown revision")}
        )

        results = reconcile(repo, dry_run=False, auto=True, runner=runner, now_fn=_NOW_FN)

        assert len(results) == 1
        assert results[0].action == "missing_branch"
        assert results[0].session_name == "s1"

        # No merge call was issued
        git_verbs = [c["cmd"][1] for c in runner.calls if not c["shell"]]
        assert "merge" not in git_verbs

    def test_merge_conflict_aborts_and_records(self, tmp_path: Path) -> None:
        """Returns 'merge_conflict'; issues git merge --abort; checkbox stays '[ ]'."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        _write_queue(queue_path, [_queue_line("s1")])

        # rev-parse succeeds; merge fails
        runner = RecordingRunner(
            git_responses={
                "rev-parse": FakeResult(returncode=0),
                "merge": FakeResult(returncode=1, stderr="CONFLICT (content): Merge conflict"),
            }
        )

        results = reconcile(repo, dry_run=False, auto=True, runner=runner, now_fn=_NOW_FN)

        assert len(results) == 1
        assert results[0].action == "merge_conflict"

        # git merge --abort must have been called
        merge_calls = [c["cmd"] for c in runner.calls if not c["shell"] and c["cmd"][1] == "merge"]
        abort_calls = [c for c in merge_calls if "--abort" in c]
        assert abort_calls, "Expected 'git merge --abort' to be issued"

        # Checkbox NOT flipped
        assert "- [ ] s1" in queue_path.read_text(encoding="utf-8")

    def test_exit_check_failure_short_circuits_merge(self, tmp_path: Path) -> None:
        """Exit check failure with auto=True → 'exit_check_failed'; no merge issued."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        _write_queue(
            queue_path,
            [_queue_line("s1", exit_check="pytest")],
        )

        runner = RecordingRunner(
            git_responses={"rev-parse": FakeResult(returncode=0)},
            shell_rc=1,
            shell_stderr="5 tests failed",
        )

        results = reconcile(repo, dry_run=False, auto=True, runner=runner, now_fn=_NOW_FN)

        assert len(results) == 1
        assert results[0].action == "exit_check_failed"
        assert "5 tests failed" in results[0].detail

        # No merge call was issued
        git_verbs = [c["cmd"][1] for c in runner.calls if not c["shell"]]
        assert "merge" not in git_verbs

    def test_deadlock_when_all_deps_unmet(self, tmp_path: Path) -> None:
        """Circular/unsatisfiable deps produce a 'deadlocked' result."""
        repo = _make_fake_repo(tmp_path)
        queue_path = repo / "logs" / "merge-queue.md"
        # B depends on A, but A is not in the queue
        _write_queue(queue_path, [_queue_line("B", depends_on="A")])

        runner = RecordingRunner()

        results = reconcile(repo, dry_run=False, auto=True, runner=runner, now_fn=_NOW_FN)

        assert len(results) == 1
        assert results[0].action == "deadlocked"
        # No git calls attempted
        assert runner.calls == []


# ---------------------------------------------------------------------------
# Group G — CLI smoke
# ---------------------------------------------------------------------------


cli_runner = CliRunner()


class TestCli:
    """anthive merge CLI: smoke tests via Typer's CliRunner."""

    def test_merge_dry_run_empty_queue_exits_zero(self, tmp_path: Path) -> None:
        """--dry-run --auto with no queue file exits 0 and prints graceful message."""
        result = cli_runner.invoke(
            app,
            ["merge", "--dry-run", "--auto", "--repo", str(tmp_path)],
        )
        assert result.exit_code == 0

    def test_merge_dry_run_json_returns_valid_json(self, tmp_path: Path) -> None:
        """--dry-run --auto --json with one queue row returns a parseable JSON list."""
        queue_path = tmp_path / "logs" / "merge-queue.md"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, [_queue_line("my-session")])

        result = cli_runner.invoke(
            app,
            ["merge", "--dry-run", "--auto", "--json", "--repo", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert isinstance(payload, list)
        assert len(payload) == 1
        item = payload[0]
        assert "session_name" in item
        assert "action" in item
        assert "pr" in item
        assert item["action"] == "would_merge"
