"""Shared pytest fixtures for the anthive test suite.

Centralises scaffolding that was previously duplicated across the unit and
integration tests (fake task docs, fake agent files, fake swarm.toml,
recording subprocess runner) and adds a small set of fixtures used by the
E2E layer (real git repo, fake `claude` binary on PATH).

E2E tests are tagged with ``@pytest.mark.e2e`` and selected via::

    pytest -m e2e            # only e2e
    pytest -m "not e2e"      # everything else (fast)
    pytest                   # both (default)

The conftest also silences the OTLP exporter during tests by pointing
``OTEL_EXPORTER_OTLP_ENDPOINT`` at an unreachable but quiet endpoint and
disabling the SDK so background exporter retries don't pollute test output.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end CLI scenarios driving the real `anthive` entry point.",
    )


# ---------------------------------------------------------------------------
# Quiet the OTLP exporter for the duration of the test session.
# Without this, observability.init_tracing() spins up a background span
# exporter that retries against http://localhost:9999/otel and prints
# noisy warnings after the suite has already finished.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _silence_otel() -> None:
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    # In case anything still tries to export, send it nowhere reachable
    # but with a non-default URL so it's clearly opted out.
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:0/disabled")


# ---------------------------------------------------------------------------
# Sample task / agent / swarm.toml content
# ---------------------------------------------------------------------------


_TASK_TEMPLATE = """\
---
id: {task_id}
title: {title}
status: {status}
effort: {effort}
budget_usd: {budget_usd}
agent: {agent}
depends_on: {depends_on}
touches_paths:{touches_paths}
---

# {title}

Task body for {task_id}.
"""


_AGENT_TEMPLATE = """\
---
name: {name}
description: Test agent — does nothing real.
---

# {name}

You are a test agent. Do absolutely nothing.
"""


_SWARM_TOML = """\
[project]
name = "anthive-test"

[dispatcher]
default = "local"

[dispatcher.local]
auth = "subscription"
worktree_dir = "worktrees/"
tmux_session_prefix = "anthive-test-"
default_model = "sonnet"
max_concurrent_sessions = 4

[dispatcher.cloud]
auth = "api_key"
api_key_env = "ANTHROPIC_API_KEY"
budget_cap_usd = 5.00
require_confirm = true
max_concurrent = 3
daily_budget_usd = 50.00

[observability]
langfuse_url = "http://localhost:3000"
otel_endpoint = "http://localhost:0/disabled"

[paths]
tasks_dir = "tasks/"
sessions_dir = "logs/sessions/"
merge_queue = "logs/merge-queue.md"
decisions_dir = "logs/decisions/"
archive_dir = "logs/archive/"
prompts_dir = "prompts/"

[agents]
fallback = "python-developer"
heuristic_match = true

[git]
branch_prefix = "session/"
merge_strategy = "no-ff"
allow_force_push = false
respect_hooks = true
"""


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------


WriteTaskFn = Callable[..., Path]
WriteAgentFn = Callable[[str], Path]


# ---------------------------------------------------------------------------
# Fixtures: project scaffolding (no git)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_swarm_toml(tmp_path: Path) -> Path:
    """Write a minimal valid ``swarm.toml`` to ``tmp_path`` and return it."""
    path = tmp_path / "swarm.toml"
    path.write_text(_SWARM_TOML, encoding="utf-8")
    return path


@pytest.fixture
def write_agent(tmp_path: Path) -> WriteAgentFn:
    """Factory: write ``.claude/agents/dev/<name>.md`` and return the path."""

    def _write(name: str = "python-developer") -> Path:
        agents_dir = tmp_path / ".claude" / "agents" / "dev"
        agents_dir.mkdir(parents=True, exist_ok=True)
        path = agents_dir / f"{name}.md"
        path.write_text(_AGENT_TEMPLATE.format(name=name), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def write_task(tmp_path: Path) -> WriteTaskFn:
    """Factory: write ``tasks/<task_id>.md`` with sane defaults."""

    def _write(
        task_id: str,
        *,
        title: str = "Test task",
        status: str = "ready",
        effort: str = "S",
        budget_usd: float = 0,
        agent: str = "python-developer",
        depends_on: list[str] | None = None,
        touches_paths: list[str] | None = None,
    ) -> Path:
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        deps = depends_on or []
        touches = touches_paths or []
        deps_yaml = "[" + ", ".join(deps) + "]"
        if touches:
            touches_yaml = "\n" + "\n".join(f"  - {p}" for p in touches)
        else:
            touches_yaml = " []"

        body = _TASK_TEMPLATE.format(
            task_id=task_id,
            title=title,
            status=status,
            effort=effort,
            budget_usd=budget_usd,
            agent=agent,
            depends_on=deps_yaml,
            touches_paths=touches_yaml,
        )
        path = tasks_dir / f"{task_id}.md"
        path.write_text(body, encoding="utf-8")
        return path

    return _write


@pytest.fixture
def project_repo(
    tmp_path: Path,
    fake_swarm_toml: Path,
    write_agent: WriteAgentFn,
) -> Path:
    """A non-git anthive project: ``swarm.toml`` + a default agent file.

    Returns the project root (``tmp_path``). Tests add tasks via ``write_task``.
    """
    write_agent("python-developer")
    return tmp_path


# ---------------------------------------------------------------------------
# Fixtures: real git repo for E2E
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "anthive-test",
            "GIT_AUTHOR_EMAIL": "test@anthive.local",
            "GIT_COMMITTER_NAME": "anthive-test",
            "GIT_COMMITTER_EMAIL": "test@anthive.local",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(project_repo: Path) -> Path:
    """A real git repository on top of ``project_repo``.

    Initialises ``main``, configures a deterministic identity, commits the
    seed files (swarm.toml + agent file). E2E scenarios that need real git
    semantics (worktree, branches, merge dry-run) depend on this fixture.
    """
    if shutil.which("git") is None:  # pragma: no cover - CI always has git
        pytest.skip("git not available on PATH")

    _git(project_repo, "init", "-b", "main")
    _git(project_repo, "config", "user.email", "test@anthive.local")
    _git(project_repo, "config", "user.name", "anthive-test")
    _git(project_repo, "add", "-A")
    _git(project_repo, "commit", "-m", "seed: swarm.toml + default agent")
    return project_repo


# ---------------------------------------------------------------------------
# Fixture: fake `claude` CLI binary on PATH
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_claude_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Place a fake ``claude`` binary on PATH that records its invocations.

    The binary is a shell script that appends each invocation (cwd + argv)
    to ``<tmp_path>/.claude-calls.log`` and exits 0. Useful for E2E tests
    that exercise dispatch paths without invoking real Claude Code.
    """
    bin_dir = tmp_path / ".bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / ".claude-calls.log"
    script = bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env bash\n" f'echo "$(pwd)\t$*" >> "{log}"\n' "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log
