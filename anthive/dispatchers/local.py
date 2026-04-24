"""anthive local dispatcher — git worktree + tmux + claude CLI.

Every external side-effect goes through injectable helpers so the dispatcher
can be exercised in tests without touching the real filesystem, git, or tmux.

Public API:
    LocalDispatcher(config, observability, *, runner, which_fn) -> Dispatcher
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..composer import find_agent, session_id_for, slugify
from ..schemas import SessionLogFrontmatter, TaskFrontmatter, parse_session_log, write_session_log
from .base import AlreadyDispatchedError, Dispatcher, PreflightError, SessionHandle


__all__ = ["LocalDispatcher", "_default_runner"]


# ---------------------------------------------------------------------------
# Default subprocess runner
# ---------------------------------------------------------------------------


def _default_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Run *cmd* via subprocess.run with safe defaults.

    All external commands go through this function (or the stub injected in
    tests).  Using ``capture_output=True`` keeps stdout/stderr out of the
    terminal; callers inspect ``result.stdout`` when they need output.
    """
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


# ---------------------------------------------------------------------------
# LocalDispatcher
# ---------------------------------------------------------------------------


class LocalDispatcher(Dispatcher):
    """Dispatch tasks via git worktree + tmux + claude CLI (local Max subscription).

    Args:
        config:       Dict from ``swarm.toml``'s ``[dispatcher.local]`` section
                      (already merged with defaults by ``load_config``).
        observability: Dict from ``swarm.toml``'s ``[observability]`` section.
                       Controls OTEL env vars set in the child process.
        runner:       Callable with the same signature as ``subprocess.run``.
                      Inject a stub in tests to avoid real side-effects.
        which_fn:     Callable matching ``shutil.which``.  Injectable for tests.
    """

    def __init__(
        self,
        config: dict[str, Any],
        observability: dict[str, Any] | None = None,
        *,
        runner: Callable[..., Any] | None = None,
        which_fn: Callable[[str], str | None] | None = None,
    ) -> None:
        self.config = config
        self.observability = observability or {}
        self.runner = runner or _default_runner
        self._which = which_fn or shutil.which

    # ------------------------------------------------------------------
    # Public interface (Dispatcher ABC)
    # ------------------------------------------------------------------

    def dispatch(
        self,
        task: TaskFrontmatter,
        prompt: str,
        repo_root: Path,
    ) -> SessionHandle:
        """Create worktree, write session log, launch tmux, return a SessionHandle.

        Steps:
        1. Resolve slug, branch, paths.
        2. Run pre-flight checks.
        3. Capture HEAD SHA (before creating the worktree).
        4. Create the git worktree + branch.
        5. Write prompt file into worktree.
        6. Write session log to ``logs/sessions/<slug>.md``.
        7. Launch tmux session.
        8. Return SessionHandle.
        """
        paths = self._resolve_paths(task, repo_root)
        worktree_path: Path = paths["worktree"]

        self._preflight(task, repo_root, worktree_path)

        head_sha = self._get_head_sha(repo_root)
        self._create_worktree(paths["branch"], worktree_path, repo_root)

        # Write prompt into worktree so `claude < .anthive-prompt.md` works.
        prompt_file: Path = paths["prompt_file"]
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt, encoding="utf-8")

        # Write the session log.
        self._write_session_log(task, paths, head_sha)

        # Build child-process env.
        child_env = self._otel_env(paths["slug"], task)

        # Launch tmux.
        self._launch_tmux(
            pane_name=paths["pane_name"],
            worktree=worktree_path,
            prompt_file=prompt_file,
            env=child_env,
        )

        return SessionHandle(
            session_id=session_id_for(task.id),
            task_id=task.id,
            slug=paths["slug"],
            branch=paths["branch"],
            worktree=worktree_path,
            container=paths["pane_name"],
            log_path=paths["log_path"],
            mode="local",
        )

    def status(self, handle: SessionHandle) -> str:
        """Read the session log and return the ``status`` field."""
        fm = parse_session_log(handle.log_path)
        return fm.status

    def tail(self, handle: SessionHandle, lines: int = 20) -> str:
        """Return the last *lines* lines of tmux output.

        Returns an empty string if the pane no longer exists (best-effort).
        """
        try:
            result = self.runner(
                ["tmux", "capture-pane", "-t", handle.container, "-p", "-S", f"-{lines}"],
                check=False,
            )
            return result.stdout or ""
        except Exception:  # noqa: BLE001
            return ""

    def shutdown(self, handle: SessionHandle) -> None:
        """Kill the tmux session.  Best-effort: swallow errors if already gone."""
        try:
            self.runner(["tmux", "kill-session", "-t", handle.container], check=False)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Private helpers (all testable by injecting runner / which_fn)
    # ------------------------------------------------------------------

    def _resolve_paths(self, task: TaskFrontmatter, repo_root: Path) -> dict[str, Any]:
        """Compute all derived paths and names for a task dispatch.

        Returns a dict with keys:
            slug, worktree, branch, log_path, pane_name, prompt_file
        """
        slug = slugify(task.id)
        worktree_dir = self.config.get("worktree_dir", "worktrees/")
        prefix = self.config.get("tmux_session_prefix", "anthive-")
        worktree = repo_root / worktree_dir.rstrip("/") / slug
        branch = f"session/{slug}"
        log_path = repo_root / "logs" / "sessions" / f"{slug}.md"
        pane_name = f"{prefix}{slug}"
        prompt_file = worktree / ".anthive-prompt.md"
        return {
            "slug": slug,
            "worktree": worktree,
            "branch": branch,
            "log_path": log_path,
            "pane_name": pane_name,
            "prompt_file": prompt_file,
        }

    def _preflight(
        self,
        task: TaskFrontmatter,
        repo_root: Path,
        worktree_path: Path,
    ) -> None:
        """Run all pre-flight checks; raise PreflightError on any failure.

        Checks (in order):
        1. ``tmux`` on PATH.
        2. ``claude`` on PATH.
        3. Inside a git repo (``repo_root/.git`` exists).
        4. Target worktree path is free.
        5. Agent definition file exists under ``.claude/agents/``.
        """
        if self._which("tmux") is None:
            raise PreflightError(
                "tmux not found on PATH. "
                "Install tmux (e.g. brew install tmux) before dispatching locally."
            )

        if self._which("claude") is None:
            raise PreflightError(
                "claude not found on PATH. "
                "Install Claude Code CLI (npm install -g @anthropic-ai/claude-code) "
                "and authenticate before dispatching."
            )

        git_dir = repo_root / ".git"
        if not git_dir.exists():
            raise PreflightError(
                f"{repo_root} does not appear to be a git repository (.git missing)."
            )

        if worktree_path.exists():
            slug = worktree_path.name
            raise AlreadyDispatchedError(
                session_id=session_id_for(task.id),
                hint=f"Remove the worktree at {worktree_path} and the branch "
                     f"'session/{slug}' to re-dispatch.",
            )

        agent_path = find_agent(task.agent, repo_root)
        if agent_path is None:
            raise PreflightError(
                f"Agent definition for {task.agent!r} not found under "
                f"{repo_root / '.claude' / 'agents'}. "
                f"Add a file named {task.agent}.md in any subdirectory there."
            )

    def _get_head_sha(self, repo_root: Path) -> str:
        """Return the current HEAD SHA of the repository."""
        result = self.runner(["git", "rev-parse", "HEAD"], cwd=str(repo_root))
        return result.stdout.strip()

    def _create_worktree(self, branch: str, worktree_path: Path, repo_root: Path) -> None:
        """Create a git worktree at *worktree_path* on a new *branch*."""
        self.runner(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            cwd=str(repo_root),
        )

    def _write_session_log(
        self,
        task: TaskFrontmatter,
        paths: dict[str, Any],
        head_sha: str,
    ) -> None:
        """Build a SessionLogFrontmatter and write it to disk."""
        now_iso = datetime.now(timezone.utc).isoformat()
        session_id = session_id_for(task.id)
        slug: str = paths["slug"]
        model = self.config.get("default_model", "sonnet")

        fm = SessionLogFrontmatter(
            session_id=session_id,
            task_id=task.id,
            slug=slug,
            branch=paths["branch"],
            worktree=str(paths["worktree"]),
            container=paths["pane_name"],
            mode="local",
            forked_from_sha=head_sha,
            created=now_iso,  # type: ignore[arg-type]
            status="INIT",
            last_heartbeat=now_iso,  # type: ignore[arg-type]
            last_note="scaffolded by anthive dispatch",
            primary_agent=task.agent,
            model=task.prefer_model or model,
            budget_usd=task.budget_usd,
            touches_paths=task.touches_paths,
        )

        body = (
            f"# Session {session_id}\n\n"
            "**Purpose:** (filled by the session from the prompt)\n\n"
            "## Timeline\n\n"
            f"- **{now_iso}** · `INIT` · scaffolded by `anthive dispatch`\n"
        )

        log_path: Path = paths["log_path"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        write_session_log(log_path, fm, body)

    def _launch_tmux(
        self,
        pane_name: str,
        worktree: Path,
        prompt_file: Path,
        env: dict[str, str],
    ) -> None:
        """Start a detached tmux session running ``claude`` with the prompt piped in."""
        child_env = {**os.environ, **env}
        self.runner(
            [
                "tmux",
                "new-session",
                "-d",
                "-s", pane_name,
                "-c", str(worktree),
                f"claude < {prompt_file}",
            ],
            env=child_env,
        )

    def _otel_env(self, slug: str, task: TaskFrontmatter) -> dict[str, str]:
        """Return OTEL environment variables to set in the child tmux process.

        These vars are intentionally NOT set in the parent CLI process so that
        anthive's own spans are not accidentally attributed to a session.
        """
        endpoint = self.observability.get(
            "otel_endpoint", "http://localhost:3000/api/public/otel"
        )
        resource_attrs = (
            f"session.id={slug},"
            f"task.id={task.id},"
            f"agent={task.agent},"
            f"mode=local"
        )
        return {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
            "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
            "OTEL_RESOURCE_ATTRIBUTES": resource_attrs,
        }
