"""anthive heartbeat — let dispatched sessions update their own state.

The composer's prompt template instructs every session to call
``anthive heartbeat <session_id> <state> "<note>"`` on each meaningful
state change.  This module implements the file-system mutation:

    1. Resolve ``session_id`` (with optional ``sess-`` prefix) to
       ``logs/sessions/<slug>.md``.
    2. Parse the existing frontmatter via :func:`anthive.schemas.parse_session_log`.
    3. Build a fresh :class:`SessionLogFrontmatter` with the new ``status``,
       ``last_heartbeat`` and ``last_note``.
    4. Read the body, append a timeline bullet beneath the existing
       ``## Timeline`` heading.
    5. Re-write the file with :func:`anthive.schemas.write_session_log`.

Pydantic's ``Literal`` validation on ``status`` rejects unknown states with
a :class:`pydantic.ValidationError`, which the CLI surfaces as exit code 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .schemas import (
    SessionLogFrontmatter,
    _split_frontmatter,
    parse_session_log,
    write_session_log,
)

__all__ = ["heartbeat", "session_id_to_slug"]


def session_id_to_slug(session_id: str) -> str:
    """Strip an optional ``sess-`` prefix; the remainder is the log slug."""
    if session_id.startswith("sess-"):
        return session_id[len("sess-"):]
    return session_id


def heartbeat(
    repo_root: Path,
    session_id: str,
    state: str,
    note: str = "",
    *,
    sessions_dir: str | Path = "logs/sessions",
    now_fn: Callable[[], datetime] | None = None,
) -> Path:
    """Update ``logs/sessions/<slug>.md`` frontmatter + timeline.

    Args:
        repo_root: Repository root containing ``logs/sessions/``.
        session_id: Session id, with or without the ``sess-`` prefix.
        state: New status — must be one of the values accepted by
            :class:`SessionLogFrontmatter.status`.
        note: Optional one-line note recorded in ``last_note`` and the
            timeline bullet.
        sessions_dir: Directory holding session logs (relative to
            *repo_root* unless absolute). Defaults to ``logs/sessions``.
        now_fn: Optional zero-arg callable returning ``datetime`` — used by
            tests to inject a deterministic "now".

    Returns:
        Path to the updated session log file.

    Raises:
        FileNotFoundError: When the log file does not exist.
        pydantic.ValidationError: When *state* is not an accepted value.
    """
    slug = session_id_to_slug(session_id)

    sessions_path = Path(sessions_dir)
    if not sessions_path.is_absolute():
        sessions_path = repo_root / sessions_path
    log_path = sessions_path / f"{slug}.md"

    if not log_path.exists():
        raise FileNotFoundError(
            f"Session log not found: {log_path}. "
            f"Run `anthive dispatch` first or check the session id."
        )

    now_dt = (now_fn or _now_utc)()
    now_iso = now_dt.isoformat()

    existing = parse_session_log(log_path)
    updated = existing.model_copy(
        update={
            "status": state,
            "last_heartbeat": now_dt,
            "last_note": note,
        }
    )
    # Re-validate so an invalid `state` raises pydantic.ValidationError here
    # rather than silently passing through model_copy.
    updated = SessionLogFrontmatter.model_validate(updated.model_dump())

    body = _read_body(log_path)
    new_body = _append_timeline_entry(body, now_iso, state, note)

    write_session_log(log_path, updated, new_body)
    return log_path


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_body(path: Path) -> str:
    """Return the body (post-frontmatter) of a session log file."""
    text = path.read_text(encoding="utf-8")
    _, body = _split_frontmatter(text)
    return body


def _append_timeline_entry(body: str, iso_now: str, state: str, note: str) -> str:
    """Append a timeline bullet line to *body*.

    If ``## Timeline`` exists, the bullet is appended after the last existing
    bullet under that heading.  Otherwise the section is created at the end
    of the body.
    """
    bullet = f"- **{iso_now}** · `{state}` · {note}"
    if not body.endswith("\n"):
        body = body + "\n"

    if "## Timeline" not in body:
        suffix = "\n## Timeline\n\n" if body.strip() else "## Timeline\n\n"
        return body + suffix + bullet + "\n"

    # Ensure exactly one trailing newline before appending the bullet so we
    # don't accumulate blank lines on repeated heartbeats.
    trimmed = body.rstrip("\n") + "\n"
    return trimmed + bullet + "\n"
