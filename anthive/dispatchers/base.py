"""anthive dispatcher base — abstract interface, shared dataclasses, and exceptions.

All concrete dispatchers (LocalDispatcher, CloudDispatcher) implement this interface
so that the CLI can swap them without touching business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..schemas import TaskFrontmatter


__all__ = [
    "SessionHandle",
    "DispatchError",
    "AlreadyDispatchedError",
    "PreflightError",
    "Dispatcher",
]


# ---------------------------------------------------------------------------
# Session handle — returned by every Dispatcher.dispatch() call
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionHandle:
    """Immutable record describing a live or completed dispatch session.

    Carries enough context to call status(), tail(), and shutdown() without
    re-reading config or the session log.
    """

    session_id: str
    task_id: str
    slug: str
    branch: str
    worktree: Path
    container: str    # tmux session name (local) or Managed Agents session id (cloud)
    log_path: Path
    mode: str         # "local" | "cloud"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DispatchError(Exception):
    """Base exception for all dispatcher failures."""


class AlreadyDispatchedError(DispatchError):
    """Raised when a worktree or session for the given task already exists.

    Attributes:
        session_id: The session / slug that already exists.
        hint:       Human-readable message with remediation advice.
    """

    def __init__(self, session_id: str, hint: str = "") -> None:
        self.session_id = session_id
        self.hint = hint
        msg = f"Session {session_id!r} already dispatched."
        if hint:
            msg += f" {hint}"
        super().__init__(msg)


class PreflightError(DispatchError):
    """Raised when a pre-flight check fails (missing binary, missing agent, etc.)."""


# ---------------------------------------------------------------------------
# Abstract dispatcher
# ---------------------------------------------------------------------------


class Dispatcher(ABC):
    """Common interface for local + cloud dispatchers."""

    @abstractmethod
    def dispatch(
        self,
        task: TaskFrontmatter,
        prompt: str,
        repo_root: Path,
    ) -> SessionHandle:
        """Launch a session for *task* using *prompt*.

        Args:
            task:      Parsed task frontmatter.
            prompt:    Full prompt text to feed the claude session.
            repo_root: Absolute path to the repository root.

        Returns:
            A SessionHandle describing the newly created session.

        Raises:
            AlreadyDispatchedError: If the worktree / session already exists.
            PreflightError:         If a required binary or file is missing.
            DispatchError:          For any other launch failure.
        """

    @abstractmethod
    def status(self, handle: SessionHandle) -> str:
        """Return the current status string for *handle* (e.g. ``"INIT"``, ``"COOKING"``)."""

    @abstractmethod
    def tail(self, handle: SessionHandle, lines: int = 20) -> str:
        """Return the last *lines* lines of session output.

        Returns an empty string if the session pane no longer exists.
        """

    @abstractmethod
    def shutdown(self, handle: SessionHandle) -> None:
        """Gracefully stop the session described by *handle*.

        Implementations should be best-effort: do not raise if the session is
        already gone.
        """
