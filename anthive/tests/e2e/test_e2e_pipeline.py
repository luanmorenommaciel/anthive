"""End-to-end CLI scenarios for anthive.

Each test drives the real Typer entry point (``anthive.cli:app``) against a
fixture project so a regression in any inter-unit file-system contract
(scanner -> composer -> dispatcher -> heartbeat -> merger) shows up here.

E2E tests are tagged with ``@pytest.mark.e2e``::

    pytest -m e2e            # run only these
    pytest -m "not e2e"      # skip them (fast feedback loop)
    pytest                   # run everything

These tests are intentionally hermetic:
- No real ``claude`` binary is invoked.
- No real ``tmux`` server is started.
- No outbound HTTP (Langfuse / OTEL is disabled by conftest).
- Real ``git`` is used for the merge scenario; everything else is FS-only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anthive.cli import app

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_COMMANDS_WITH_REPO = {
    "scan",
    "compose",
    "dispatch",
    "watch",
    "status",
    "merge",
    "heartbeat",
}


def _invoke(runner: CliRunner, args: list[str], cwd: Path) -> object:
    """Invoke the anthive Typer app pinned to ``cwd``.

    Typer evaluates ``Path.cwd()`` once at module import time, so a plain
    ``os.chdir`` is not enough — every subcommand that takes ``--repo`` must
    receive the test's tmp_path explicitly. We inject it for the caller so
    the tests stay declarative.
    """
    if args and args[0] in _COMMANDS_WITH_REPO and "--repo" not in args:
        args = [*args, "--repo", str(cwd)]
    prev = Path.cwd()
    os.chdir(cwd)
    try:
        return runner.invoke(app, args, catch_exceptions=False)
    finally:
        os.chdir(prev)


def _seed_session_log(repo: Path, session_id: str, task_id: str, slug: str) -> Path:
    sessions_dir = repo / "logs" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{slug}.md"
    path.write_text(
        f"""---
session_id: {session_id}
slug: {slug}
branch: session/{slug}
worktree: worktrees/{slug}
container: c1
forked_from_sha: deadbeef
created: 2026-05-05T12:00:00Z
status: INIT
last_heartbeat: 2026-05-05T12:00:00Z
last_note: seeded
task_id: {task_id}
primary_agent: python-developer
---

## Timeline

- 2026-05-05T12:00:00Z · INIT · seeded
""",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# E2E-1 — scan -> compose
# ---------------------------------------------------------------------------


class TestScanCompose:
    """Scanner emits a ready task; composer turns it into a prompt file."""

    def test_scan_lists_ready_task_then_compose_writes_prompt(
        self, project_repo: Path, write_task
    ) -> None:
        write_task("p99-e2e1", title="E2E one", touches_paths=["anthive/foo.py"])
        runner = CliRunner()

        scan = _invoke(runner, ["scan", "--json"], project_repo)
        assert scan.exit_code == 0, scan.output
        payload = json.loads(scan.output)
        assert [e["id"] for e in payload["ready"]] == ["p99-e2e1"]
        assert payload["ready"][0]["agent"] == "python-developer"

        compose = _invoke(runner, ["compose", "p99-e2e1"], project_repo)
        assert compose.exit_code == 0, compose.output

        prompt = project_repo / "prompts" / "p99-e2e1.md"
        assert prompt.exists(), "composer did not write the prompt file"
        text = prompt.read_text(encoding="utf-8")
        assert "p99-e2e1" in text
        assert "python-developer" in text
        assert "session/p99-e2e1" in text


# ---------------------------------------------------------------------------
# E2E-2 — dispatch --dry-run
# ---------------------------------------------------------------------------


class TestDispatchDryRun:
    """Dispatch in dry-run mode is end-to-end without invoking tmux/claude."""

    def test_dispatch_dry_run_after_compose(self, project_repo: Path, write_task) -> None:
        write_task("p99-e2e2", title="E2E two")
        runner = CliRunner()

        compose = _invoke(runner, ["compose", "p99-e2e2"], project_repo)
        assert compose.exit_code == 0, compose.output

        dispatch = _invoke(
            runner,
            ["dispatch", "p99-e2e2", "--dry-run", "--yes"],
            project_repo,
        )
        assert dispatch.exit_code == 0, dispatch.output
        out = dispatch.output
        assert "DRY RUN" in out
        assert "p99-e2e2" in out
        # No worktree should have been created in dry-run.
        assert not (project_repo / "worktrees" / "p99-e2e2").exists()

    def test_dispatch_unknown_task_exits_nonzero(self, project_repo: Path, write_task) -> None:
        write_task("p99-real")
        runner = CliRunner()

        result = _invoke(
            runner,
            ["dispatch", "p99-ghost", "--dry-run", "--yes"],
            project_repo,
        )
        assert result.exit_code != 0
        assert "p99-ghost" in result.output


# ---------------------------------------------------------------------------
# E2E-3 — heartbeat state machine
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Heartbeat CLI updates a session log's status + timeline."""

    def test_heartbeat_advances_status(self, project_repo: Path) -> None:
        log_path = _seed_session_log(project_repo, "sess-p99-e2e3", "p99-e2e3", "p99-e2e3")
        runner = CliRunner()

        result = _invoke(
            runner,
            ["heartbeat", "sess-p99-e2e3", "COOKING", "starting work"],
            project_repo,
        )
        assert result.exit_code == 0, result.output

        text = log_path.read_text(encoding="utf-8")
        assert "status: COOKING" in text
        assert "last_note: starting work" in text

        result2 = _invoke(
            runner,
            ["heartbeat", "sess-p99-e2e3", "READY-TO-MERGE", "all green"],
            project_repo,
        )
        assert result2.exit_code == 0, result2.output
        text2 = log_path.read_text(encoding="utf-8")
        assert "status: READY-TO-MERGE" in text2
        assert "last_note: all green" in text2

    def test_heartbeat_unknown_session_fails_clean(self, project_repo: Path) -> None:
        runner = CliRunner()
        result = _invoke(
            runner,
            ["heartbeat", "sess-does-not-exist", "COOKING"],
            project_repo,
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# E2E-4 — merge --dry-run --auto
# ---------------------------------------------------------------------------


class TestMergeDryRun:
    """Merge reconciler in dry-run mode is end-to-end on a real git repo."""

    def test_merge_dry_run_emits_would_merge(self, git_repo: Path) -> None:
        queue = git_repo / "logs" / "merge-queue.md"
        queue.parent.mkdir(parents=True, exist_ok=True)
        queue.write_text(
            "# Merge Queue\n\n"
            "- [ ] p99-e2e4 · PR #1 · touches: anthive/foo.py "
            "· depends-on: none · exit_check: pytest -q\n",
            encoding="utf-8",
        )
        runner = CliRunner()

        result = _invoke(
            runner,
            ["merge", "--dry-run", "--auto", "--json"],
            git_repo,
        )
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert len(rows) == 1
        assert rows[0]["session_name"] == "p99-e2e4"
        assert rows[0]["action"] == "would_merge"


# ---------------------------------------------------------------------------
# E2E-5 — full chain: scan -> compose -> dispatch (dry) -> heartbeat -> merge
# ---------------------------------------------------------------------------


class TestFullChain:
    """One project, every step in sequence — every artifact survives the next."""

    def test_full_pipeline_artifacts_survive_each_step(self, git_repo: Path, write_task) -> None:
        task_id = "p99-e2e5"
        slug = task_id
        write_task(task_id, title="Full chain", touches_paths=["anthive/foo.py"])
        runner = CliRunner()

        # 1. scan
        scan = _invoke(runner, ["scan", "--json"], git_repo)
        assert scan.exit_code == 0, scan.output
        ids = [e["id"] for e in json.loads(scan.output)["ready"]]
        assert task_id in ids

        # 2. compose
        compose = _invoke(runner, ["compose", task_id], git_repo)
        assert compose.exit_code == 0, compose.output
        prompt = git_repo / "prompts" / f"{task_id}.md"
        assert prompt.exists()

        # 3. dispatch dry-run (must not touch worktree, but must read the prompt)
        dispatch = _invoke(runner, ["dispatch", task_id, "--dry-run", "--yes"], git_repo)
        assert dispatch.exit_code == 0, dispatch.output
        assert "DRY RUN" in dispatch.output
        assert prompt.exists(), "compose artifact lost during dispatch"

        # 4. heartbeat
        _seed_session_log(git_repo, f"sess-{slug}", task_id, slug)
        heartbeat = _invoke(
            runner,
            ["heartbeat", f"sess-{slug}", "READY-TO-MERGE", "ready"],
            git_repo,
        )
        assert heartbeat.exit_code == 0, heartbeat.output
        log_text = (git_repo / "logs" / "sessions" / f"{slug}.md").read_text("utf-8")
        assert "status: READY-TO-MERGE" in log_text

        # 5. merge dry-run
        queue = git_repo / "logs" / "merge-queue.md"
        queue.write_text(
            "# Merge Queue\n\n"
            f"- [ ] {slug} · PR #1 · touches: anthive/foo.py "
            "· depends-on: none · exit_check: pytest -q\n",
            encoding="utf-8",
        )
        merge = _invoke(runner, ["merge", "--dry-run", "--auto", "--json"], git_repo)
        assert merge.exit_code == 0, merge.output
        rows = json.loads(merge.output)
        assert rows[0]["session_name"] == slug
        assert rows[0]["action"] == "would_merge"

        # Final invariant: every prior artifact is still on disk.
        assert (git_repo / "tasks" / f"{task_id}.md").exists()
        assert prompt.exists()
        assert (git_repo / "logs" / "sessions" / f"{slug}.md").exists()
        assert queue.exists()
