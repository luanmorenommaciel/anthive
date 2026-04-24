"""Tests for anthive/dispatchers/local.py — p3 LocalDispatcher test suite.

Covers pre-flight checks, idempotency guard, worktree creation, session log
writing, OTEL env vars, tail/shutdown, and config loading.

Groups:
    A — Pre-flight (4 tests)
    B — Idempotency (1 test)
    C — Worktree + log creation (4 tests)
    D — OTEL env vars (2 tests)
    E — Tail / shutdown (2 tests)
    F — Config loading (2 tests)
    G — CLI --cloud guard (1 test)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from anthive.config import DEFAULTS, load_config
from anthive.dispatchers.base import AlreadyDispatchedError, PreflightError
from anthive.dispatchers.local import LocalDispatcher
from anthive.schemas import TaskFrontmatter, parse_session_log

# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Minimal dispatcher config (mirrors DEFAULTS["dispatcher"]["local"])
# ---------------------------------------------------------------------------

_LOCAL_CFG: dict[str, Any] = {
    "auth": "subscription",
    "worktree_dir": "worktrees/",
    "tmux_session_prefix": "anthive-",
    "default_model": "sonnet",
    "max_concurrent_sessions": 4,
}


# ---------------------------------------------------------------------------
# Fake-repo helper
# ---------------------------------------------------------------------------


def _make_fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake repo with .git, agent file, and log dir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Satisfy the git-repo check in _preflight
    (repo / ".git").mkdir()
    # Agent definition expected by _preflight / find_agent
    agent_dir = repo / ".claude" / "agents" / "python"
    agent_dir.mkdir(parents=True)
    (agent_dir / "python-developer.md").write_text(
        "# python-developer agent", encoding="utf-8"
    )
    # Log + task dirs
    (repo / "logs" / "sessions").mkdir(parents=True)
    (repo / "tasks").mkdir()
    return repo


def _make_task(
    task_id: str = "T-20260424-alpha",
    agent: str = "python-developer",
    touches_paths: list[str] | None = None,
) -> TaskFrontmatter:
    """Return a valid TaskFrontmatter with sensible defaults."""
    return TaskFrontmatter(
        id=task_id,
        title="Alpha task",
        status="ready",
        effort="S",
        budget_usd=1.0,
        agent=agent,
        depends_on=[],
        touches_paths=touches_paths or ["anthive/foo.py"],
    )


# ---------------------------------------------------------------------------
# Recording runner — records all calls; side-effects git worktree creation
# ---------------------------------------------------------------------------


class RecordingRunner:
    """Drop-in replacement for subprocess.run that records every call.

    It manufactures a fake worktree directory when 'git worktree add' is
    invoked so that subsequent writes (prompt file) succeed without a real git.
    """

    def __init__(self, head_sha: str = "abc123def456") -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
        self.head_sha = head_sha

    def __call__(self, cmd: list[str], **kw: Any) -> Any:
        self.calls.append((tuple(cmd), kw))

        if list(cmd[:3]) == ["git", "worktree", "add"]:
            # Find the path argument: cmd = [..., "-b", branch, path]
            b_idx = cmd.index("-b")
            worktree_path = Path(cmd[b_idx + 2])
            worktree_path.mkdir(parents=True, exist_ok=True)

        class _Result:
            stdout: str
            stderr: str = ""
            returncode: int = 0

        result = _Result()
        result.stdout = (
            self.head_sha if list(cmd[:2]) == ["git", "rev-parse"] else ""
        )
        return result

    def commands(self) -> list[list[str]]:
        """Return recorded command lists for easy assertion."""
        return [list(cmd) for cmd, _ in self.calls]

    def find_call(self, *prefix: str) -> tuple[tuple[str, ...], dict[str, Any]] | None:
        """Return first recorded call whose command starts with prefix."""
        for cmd, kw in self.calls:
            if list(cmd[: len(prefix)]) == list(prefix):
                return cmd, kw
        return None


# ---------------------------------------------------------------------------
# Stub which_fn helpers
# ---------------------------------------------------------------------------


def _which_all_present(name: str) -> str:
    """Pretend every binary is on PATH."""
    return f"/usr/bin/{name}"


def _which_no_tmux(name: str) -> str | None:
    """Pretend tmux is missing."""
    return None if name == "tmux" else f"/usr/bin/{name}"


def _which_no_claude(name: str) -> str | None:
    """Pretend claude is missing."""
    return None if name == "claude" else f"/usr/bin/{name}"


# ---------------------------------------------------------------------------
# Group A — Pre-flight (4 tests)
# ---------------------------------------------------------------------------


class TestPreflight:
    """Verify that _preflight raises the correct errors for missing resources."""

    def test_preflight_passes_when_all_present(self, tmp_path: Path) -> None:
        """Pre-flight does not raise when tmux, claude, .git, and agent are present."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task()
        runner = RecordingRunner()
        dispatcher = LocalDispatcher(
            _LOCAL_CFG, runner=runner, which_fn=_which_all_present
        )
        # If _preflight raises, the test fails automatically.
        handle = dispatcher.dispatch(task, "test prompt", repo)
        assert handle.task_id == task.id

    def test_preflight_fails_tmux_missing(self, tmp_path: Path) -> None:
        """PreflightError is raised when tmux is not on PATH."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task()
        dispatcher = LocalDispatcher(
            _LOCAL_CFG,
            runner=RecordingRunner(),
            which_fn=_which_no_tmux,
        )
        with pytest.raises(PreflightError, match="tmux"):
            dispatcher.dispatch(task, "prompt", repo)

    def test_preflight_fails_claude_missing(self, tmp_path: Path) -> None:
        """PreflightError is raised when the claude CLI is not on PATH."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task()
        dispatcher = LocalDispatcher(
            _LOCAL_CFG,
            runner=RecordingRunner(),
            which_fn=_which_no_claude,
        )
        with pytest.raises(PreflightError, match="claude"):
            dispatcher.dispatch(task, "prompt", repo)

    def test_preflight_fails_agent_missing(self, tmp_path: Path) -> None:
        """PreflightError is raised when the agent definition file is not found."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task(agent="nonexistent-agent")
        dispatcher = LocalDispatcher(
            _LOCAL_CFG,
            runner=RecordingRunner(),
            which_fn=_which_all_present,
        )
        with pytest.raises(PreflightError, match="nonexistent-agent"):
            dispatcher.dispatch(task, "prompt", repo)


# ---------------------------------------------------------------------------
# Group B — Idempotency (1 test)
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Verify that re-dispatching the same task raises AlreadyDispatchedError."""

    def test_redispatch_raises_already_dispatched(self, tmp_path: Path) -> None:
        """AlreadyDispatchedError raised when the worktree path already exists."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task()
        runner = RecordingRunner()
        dispatcher = LocalDispatcher(
            _LOCAL_CFG, runner=runner, which_fn=_which_all_present
        )

        # Pre-create the worktree path to simulate a previous dispatch.
        from anthive.composer import slugify

        slug = slugify(task.id)
        worktree = repo / "worktrees" / slug
        worktree.mkdir(parents=True)

        # Track how many calls exist before the failed dispatch attempt.
        calls_before = len(runner.calls)

        with pytest.raises(AlreadyDispatchedError):
            dispatcher.dispatch(task, "prompt", repo)

        # No git worktree add call should have been made.
        worktree_calls = [
            cmd for cmd in runner.commands()[calls_before:]
            if list(cmd[:3]) == ["git", "worktree", "add"]
        ]
        assert worktree_calls == [], "git worktree add must not be called on re-dispatch"


# ---------------------------------------------------------------------------
# Group C — Worktree + log creation (4 tests)
# ---------------------------------------------------------------------------


class TestWorktreeAndLog:
    """Verify worktree creation, session log content, and prompt file placement."""

    @pytest.fixture()
    def repo(self, tmp_path: Path) -> Path:
        """Provide a fresh fake repo for each test."""
        return _make_fake_repo(tmp_path)

    @pytest.fixture()
    def runner(self) -> RecordingRunner:
        """Provide a fresh RecordingRunner."""
        return RecordingRunner(head_sha="abc123def456")

    @pytest.fixture()
    def task(self) -> TaskFrontmatter:
        """Provide a standard task."""
        return _make_task(touches_paths=["anthive/foo.py", "anthive/bar.py"])

    @pytest.fixture()
    def handle_and_runner(
        self, repo: Path, runner: RecordingRunner, task: TaskFrontmatter
    ) -> tuple[Any, RecordingRunner]:
        """Dispatch once and return (handle, runner) for inspection."""
        dispatcher = LocalDispatcher(
            _LOCAL_CFG, runner=runner, which_fn=_which_all_present
        )
        handle = dispatcher.dispatch(task, "hello prompt", repo)
        return handle, runner

    def test_git_worktree_add_called_with_correct_branch_and_path(
        self, handle_and_runner: tuple[Any, RecordingRunner], task: TaskFrontmatter
    ) -> None:
        """git worktree add must include -b session/<slug> and the resolved path."""
        from anthive.composer import slugify

        handle, runner = handle_and_runner
        slug = slugify(task.id)
        found = runner.find_call("git", "worktree", "add")
        assert found is not None, "git worktree add call not recorded"
        cmd, _ = found
        cmd_list = list(cmd)
        assert "-b" in cmd_list
        b_idx = cmd_list.index("-b")
        assert cmd_list[b_idx + 1] == f"session/{slug}"
        assert cmd_list[b_idx + 2].endswith(slug)

    def test_session_log_written_with_valid_frontmatter(
        self,
        handle_and_runner: tuple[Any, RecordingRunner],
        task: TaskFrontmatter,
    ) -> None:
        """Session log must parse to a valid SessionLogFrontmatter with correct fields."""
        from anthive.composer import session_id_for, slugify

        handle, _ = handle_and_runner
        slug = slugify(task.id)

        assert handle.log_path.exists(), "Session log file was not created"
        fm = parse_session_log(handle.log_path)

        assert fm.session_id == session_id_for(task.id)
        assert fm.slug == slug
        assert fm.task_id == task.id
        assert fm.branch == f"session/{slug}"
        assert fm.worktree.endswith(slug)
        assert fm.mode == "local"
        assert fm.status == "INIT"
        assert fm.forked_from_sha == "abc123def456"
        assert fm.primary_agent == task.agent
        assert fm.touches_paths == task.touches_paths

    def test_prompt_file_written_into_worktree(
        self, handle_and_runner: tuple[Any, RecordingRunner]
    ) -> None:
        """The prompt file .anthive-prompt.md must exist inside the worktree."""
        handle, _ = handle_and_runner
        prompt_file = handle.worktree / ".anthive-prompt.md"
        assert prompt_file.exists(), ".anthive-prompt.md not written into worktree"
        assert prompt_file.read_text(encoding="utf-8") == "hello prompt"

    def test_returned_handle_has_expected_fields(
        self,
        handle_and_runner: tuple[Any, RecordingRunner],
        task: TaskFrontmatter,
    ) -> None:
        """Returned SessionHandle must carry correct task_id, mode, container, log_path."""
        handle, _ = handle_and_runner
        prefix = _LOCAL_CFG["tmux_session_prefix"]

        assert handle.task_id == task.id
        assert handle.mode == "local"
        assert handle.container.startswith(prefix)
        assert handle.log_path.exists()


# ---------------------------------------------------------------------------
# Group D — OTEL env vars (2 tests)
# ---------------------------------------------------------------------------


class TestOtelEnvVars:
    """Verify OTEL variables are injected into the tmux launch environment."""

    def _dispatch_and_find_tmux_call(
        self,
        repo: Path,
        task: TaskFrontmatter,
        observability: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Return the env dict passed to the tmux new-session runner call."""
        runner = RecordingRunner()
        dispatcher = LocalDispatcher(
            _LOCAL_CFG,
            observability=observability,
            runner=runner,
            which_fn=_which_all_present,
        )
        dispatcher.dispatch(task, "prompt", repo)

        tmux_call = runner.find_call("tmux", "new-session")
        assert tmux_call is not None, "tmux new-session call not found"
        _, kw = tmux_call
        env: dict[str, str] = kw.get("env", {})
        return env

    def test_tmux_receives_required_otel_env_vars(self, tmp_path: Path) -> None:
        """tmux new-session env must contain all required OTEL variables."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task()
        env = self._dispatch_and_find_tmux_call(repo, task)

        assert env.get("CLAUDE_CODE_ENABLE_TELEMETRY") == "1"
        assert env.get("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA") == "1"
        assert env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "") != ""

        resource_attrs = env.get("OTEL_RESOURCE_ATTRIBUTES", "")
        from anthive.composer import slugify

        slug = slugify(task.id)
        assert f"session.id={slug}" in resource_attrs
        assert f"task.id={task.id}" in resource_attrs
        assert f"agent={task.agent}" in resource_attrs
        assert "mode=local" in resource_attrs

    def test_otel_endpoint_comes_from_observability_config(self, tmp_path: Path) -> None:
        """Custom otel_endpoint in observability config must propagate to the tmux env."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task()
        custom_endpoint = "http://custom-collector:9000/otel"
        env = self._dispatch_and_find_tmux_call(
            repo,
            task,
            observability={"otel_endpoint": custom_endpoint},
        )
        assert env.get("OTEL_EXPORTER_OTLP_ENDPOINT") == custom_endpoint


# ---------------------------------------------------------------------------
# Group E — Tail / shutdown (2 tests)
# ---------------------------------------------------------------------------


class TestTailAndShutdown:
    """Verify tail() and shutdown() issue the correct tmux commands."""

    def _make_handle(self, tmp_path: Path) -> tuple[Any, Any]:
        """Return (handle, dispatcher) after a successful dispatch."""
        repo = _make_fake_repo(tmp_path)
        task = _make_task()
        runner = RecordingRunner()
        dispatcher = LocalDispatcher(
            _LOCAL_CFG, runner=runner, which_fn=_which_all_present
        )
        handle = dispatcher.dispatch(task, "prompt", repo)
        # Replace runner with a fresh one for the tail/shutdown assertions.
        fresh_runner = RecordingRunner()
        dispatcher.runner = fresh_runner
        return handle, dispatcher, fresh_runner

    def test_tail_invokes_tmux_capture_pane(self, tmp_path: Path) -> None:
        """tail() must call tmux capture-pane with the correct pane name."""
        handle, dispatcher, runner = self._make_handle(tmp_path)
        dispatcher.tail(handle, lines=10)

        found = runner.find_call("tmux", "capture-pane")
        assert found is not None, "tmux capture-pane not called"
        cmd, _ = found
        cmd_list = list(cmd)
        assert "-t" in cmd_list
        assert cmd_list[cmd_list.index("-t") + 1] == handle.container
        # -S flag must be present and the lines value negative
        assert "-S" in cmd_list
        assert "-10" in cmd_list

    def test_shutdown_runs_kill_session_and_tolerates_failure(
        self, tmp_path: Path
    ) -> None:
        """shutdown() must issue tmux kill-session and not raise on failure."""

        class FailingRunner:
            """Raises CalledProcessError for every call."""

            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def __call__(self, cmd: list[str], **kw: Any) -> Any:
                self.calls.append(list(cmd))
                raise subprocess.CalledProcessError(1, cmd)

        repo = _make_fake_repo(tmp_path)
        task = _make_task()

        # Dispatch with a recording runner, then swap to the failing runner.
        good_runner = RecordingRunner()
        dispatcher = LocalDispatcher(
            _LOCAL_CFG, runner=good_runner, which_fn=_which_all_present
        )
        handle = dispatcher.dispatch(task, "prompt", repo)

        fail_runner = FailingRunner()
        dispatcher.runner = fail_runner

        # Must not raise.
        dispatcher.shutdown(handle)

        kill_calls = [c for c in fail_runner.calls if c[:3] == ["tmux", "kill-session", "-t"]]
        assert kill_calls, "tmux kill-session -t must have been issued"


# ---------------------------------------------------------------------------
# Group F — Config loading (2 tests)
# ---------------------------------------------------------------------------


class TestConfigLoading:
    """Verify load_config returns DEFAULTS when no swarm.toml exists, and merges correctly."""

    def test_load_config_returns_defaults_for_empty_repo(self, tmp_path: Path) -> None:
        """load_config on a repo without swarm.toml must return the full DEFAULTS."""
        cfg = load_config(tmp_path)
        assert cfg["dispatcher"]["default"] == "local"
        assert cfg["dispatcher"]["local"]["max_concurrent_sessions"] == 4
        assert cfg["dispatcher"]["local"]["tmux_session_prefix"] == "anthive-"
        assert cfg["dispatcher"]["local"]["default_model"] == "sonnet"

    def test_load_config_deep_merges_user_values_over_defaults(
        self, tmp_path: Path
    ) -> None:
        """User swarm.toml values override specific keys while retaining other defaults."""
        swarm_toml = tmp_path / "swarm.toml"
        swarm_toml.write_text(
            "[dispatcher.local]\n"
            'max_concurrent_sessions = 8\n'
            'default_model = "opus"\n',
            encoding="utf-8",
        )
        cfg = load_config(tmp_path)
        # Overridden values
        assert cfg["dispatcher"]["local"]["max_concurrent_sessions"] == 8
        assert cfg["dispatcher"]["local"]["default_model"] == "opus"
        # Retained defaults
        assert cfg["dispatcher"]["local"]["tmux_session_prefix"] == "anthive-"
        assert cfg["dispatcher"]["default"] == "local"


# ---------------------------------------------------------------------------
# Group G — CLI --cloud guard (1 test, optional)
# ---------------------------------------------------------------------------


class TestCliCloudGuard:
    """Verify that anthive dispatch --cloud exits with code 2."""

    def test_dispatch_cloud_exits_code_2(self) -> None:
        """anthive dispatch --cloud must exit 2 with a message about p6 or Cloud."""
        from typer.testing import CliRunner

        from anthive.cli import app

        # mix_stderr=True (default) routes stderr into result.output so we can
        # check both streams in a single string without accessing result.stderr
        # separately (which raises ValueError when not captured apart).
        cli_runner = CliRunner(mix_stderr=True)
        result = cli_runner.invoke(app, ["dispatch", "--cloud"])
        assert result.exit_code == 2
        output = result.output or ""
        assert any(kw in output for kw in ("p6", "Cloud", "cloud", "not yet"))
