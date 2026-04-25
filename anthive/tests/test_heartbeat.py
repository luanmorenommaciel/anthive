"""Tests for ``anthive heartbeat`` — session state updates."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from anthive.cli import app
from anthive.heartbeat import heartbeat, session_id_to_slug
from anthive.schemas import (
    SessionLogFrontmatter,
    parse_session_log,
    write_session_log,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_FAKE_NOW = datetime(2026, 4, 25, 10, 30, tzinfo=timezone.utc)


def _seed_log(
    sessions_dir: Path,
    slug: str,
    *,
    status: str = "INIT",
    last_note: str = "scaffolded",
    body: str | None = None,
) -> Path:
    """Write a minimal valid session log via the canonical serialiser."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    fm = SessionLogFrontmatter(
        session_id=f"sess-{slug}",
        slug=slug,
        branch=f"session/{slug}",
        worktree=f"worktrees/{slug}",
        container=f"anthive-{slug}",
        forked_from_sha="abc1234",
        created=_EPOCH,
        status=status,  # type: ignore[arg-type]
        last_heartbeat=_EPOCH,
        last_note=last_note,
        task_id=f"T-20260425-{slug}",
    )
    if body is None:
        body = (
            f"# Session sess-{slug}\n\n"
            "## Timeline\n\n"
            "- **1970-01-01T00:00:00+00:00** · `INIT` · scaffolded\n"
        )
    path = sessions_dir / f"{slug}.md"
    write_session_log(path, fm, body)
    return path


class TestHeartbeat:
    def test_happy_path_updates_frontmatter(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        _seed_log(sessions, "foo")

        log_path = heartbeat(
            tmp_path,
            "sess-foo",
            "COOKING",
            "starting work",
            now_fn=lambda: _FAKE_NOW,
        )

        assert log_path == sessions / "foo.md"
        fm = parse_session_log(log_path)
        assert fm.status == "COOKING"
        assert fm.last_note == "starting work"
        assert fm.last_heartbeat == _FAKE_NOW

    def test_happy_path_appends_timeline_bullet(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        path = _seed_log(sessions, "foo")

        heartbeat(
            tmp_path,
            "sess-foo",
            "COOKING",
            "starting work",
            now_fn=lambda: _FAKE_NOW,
        )

        text = path.read_text(encoding="utf-8")
        # New bullet present with state and note.
        assert (
            "- **2026-04-25T10:30:00+00:00** · `COOKING` · starting work"
            in text
        )
        # Original bullet preserved.
        assert "- **1970-01-01T00:00:00+00:00** · `INIT` · scaffolded" in text

    def test_session_id_without_prefix_resolves(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        _seed_log(sessions, "foo")

        # Pass session_id with no `sess-` prefix; should still resolve to foo.md
        log_path = heartbeat(
            tmp_path, "foo", "COOKING", "no prefix", now_fn=lambda: _FAKE_NOW
        )
        assert log_path == sessions / "foo.md"

    def test_sess_prefix_stripped(self) -> None:
        assert session_id_to_slug("sess-foo") == "foo"
        assert session_id_to_slug("foo") == "foo"
        # Only the leading occurrence is stripped.
        assert session_id_to_slug("sess-sess-foo") == "sess-foo"

    def test_missing_log_raises_file_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "logs" / "sessions").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            heartbeat(tmp_path, "sess-ghost", "COOKING", "n/a")

    def test_invalid_state_raises_validation_error(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        _seed_log(sessions, "foo")

        with pytest.raises(ValidationError):
            heartbeat(tmp_path, "sess-foo", "BOGUS-STATE", "nope")

    def test_round_trip_preserves_other_fields(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        path = _seed_log(sessions, "foo")
        before = parse_session_log(path)

        heartbeat(
            tmp_path,
            "sess-foo",
            "READY-TO-MERGE",
            "exit-check green",
            now_fn=lambda: _FAKE_NOW,
        )

        after = parse_session_log(path)
        assert after.session_id == before.session_id
        assert after.slug == before.slug
        assert after.branch == before.branch
        assert after.worktree == before.worktree
        assert after.container == before.container
        assert after.forked_from_sha == before.forked_from_sha
        assert after.task_id == before.task_id
        # Mutated fields
        assert after.status == "READY-TO-MERGE"
        assert after.last_note == "exit-check green"
        assert after.last_heartbeat == _FAKE_NOW

    def test_timeline_append_preserves_prior_entries(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        path = _seed_log(sessions, "foo")

        heartbeat(tmp_path, "sess-foo", "COOKING", "first", now_fn=lambda: _FAKE_NOW)
        later = datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc)
        heartbeat(tmp_path, "sess-foo", "CHECKPOINT", "second", now_fn=lambda: later)

        text = path.read_text(encoding="utf-8")
        assert "INIT` · scaffolded" in text
        assert "COOKING` · first" in text
        assert "CHECKPOINT` · second" in text
        # Order: scaffolded < first < second
        i_init = text.index("INIT` · scaffolded")
        i_first = text.index("COOKING` · first")
        i_second = text.index("CHECKPOINT` · second")
        assert i_init < i_first < i_second

    def test_empty_note_defaults_to_empty_string(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        path = _seed_log(sessions, "foo")

        heartbeat(tmp_path, "sess-foo", "COOKING", now_fn=lambda: _FAKE_NOW)

        fm = parse_session_log(path)
        assert fm.last_note == ""
        assert "`COOKING` · " in path.read_text(encoding="utf-8")


class TestHeartbeatCLI:
    def test_cli_happy_path(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        _seed_log(sessions, "foo")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "heartbeat",
                "sess-foo",
                "COOKING",
                "via cli",
                "--repo",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        fm = parse_session_log(sessions / "foo.md")
        assert fm.status == "COOKING"
        assert fm.last_note == "via cli"

    def test_cli_missing_log_exits_one(self, tmp_path: Path) -> None:
        (tmp_path / "logs" / "sessions").mkdir(parents=True)

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "heartbeat",
                "sess-ghost",
                "COOKING",
                "n/a",
                "--repo",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 1
        assert "Session log not found" in result.output

    def test_cli_invalid_state_exits_two(self, tmp_path: Path) -> None:
        sessions = tmp_path / "logs" / "sessions"
        _seed_log(sessions, "foo")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "heartbeat",
                "sess-foo",
                "NOPE",
                "bad",
                "--repo",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2
