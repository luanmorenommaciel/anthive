"""Tests for anthive/schemas.py — p0 contract validation.

Covers all four file-system contracts:
  - Contract 1: TaskFrontmatter
  - Contract 2: ReadyList (JSON)
  - Contract 3: SessionLogFrontmatter
  - Contract 4: MergeQueueRow

Groups A–E mirror the test plan in tasks/p0.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from anthive.schemas import (
    MergeQueueRow,
    ReadyList,
    SessionLogFrontmatter,
    TaskFrontmatter,
    _split_frontmatter,
    append_merge_queue_row,
    parse_merge_queue,
    parse_session_log,
    parse_task_doc,
    serialize_merge_queue_row,
    write_session_log,
)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "tasks/agentswarm/contracts"
REF_LOGS = REPO_ROOT / "examples/reference-logs"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Group A — TaskFrontmatter
# ---------------------------------------------------------------------------


class TestTaskFrontmatter:
    """Contract 1: TaskFrontmatter parsed from tasks/*.md YAML frontmatter."""

    def test_parses_example_file(self) -> None:
        """Example task.example.md file parses without error."""
        fm = parse_task_doc(CONTRACTS / "task.example.md")
        assert fm is not None

    def test_required_fields_present(self) -> None:
        """All required fields are populated after parsing the example file."""
        fm = parse_task_doc(CONTRACTS / "task.example.md")
        assert fm is not None
        assert fm.id == "T-20260424-card-violator-fix"
        assert fm.title == "Fix card_validator alias bug"
        assert fm.status == "ready"
        assert fm.effort == "S"
        assert fm.budget_usd == 0
        assert fm.agent == "llm-evaluator-designer"
        assert isinstance(fm.depends_on, list)
        assert isinstance(fm.touches_paths, list)
        assert len(fm.touches_paths) == 2

    def test_optional_fields_default_when_omitted(self, tmp_path: Path) -> None:
        """Optional fields (source, prefer_model, mode, etc.) default to None or []."""
        minimal_md = (
            "---\n"
            "id: p1-minimal-task\n"
            "title: Minimal Task\n"
            "status: ready\n"
            "effort: XS\n"
            "budget_usd: 0\n"
            "agent: python-developer\n"
            "depends_on: []\n"
            "touches_paths:\n"
            "  - src/foo.py\n"
            "---\n"
            "\n"
            "# Body\n"
        )
        doc = tmp_path / "minimal.md"
        doc.write_text(minimal_md, encoding="utf-8")
        fm = parse_task_doc(doc)
        assert fm is not None
        assert fm.source is None
        assert fm.created is None
        assert fm.prefer_model is None
        assert fm.mode is None
        assert fm.max_turns is None
        assert fm.tags == []

    def test_invalid_status_raises_validation_error(self) -> None:
        """An unrecognised status value triggers a ValidationError."""
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="p1-bad-status",
                title="x",
                status="INVALID",  # type: ignore[arg-type]
                effort="S",
                budget_usd=0,
                agent="dev",
                depends_on=[],
                touches_paths=[],
            )

    def test_invalid_effort_raises_validation_error(self) -> None:
        """An unrecognised effort value triggers a ValidationError."""
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="p1-bad-effort",
                title="x",
                status="ready",
                effort="HUGE",  # type: ignore[arg-type]
                budget_usd=0,
                agent="dev",
                depends_on=[],
                touches_paths=[],
            )

    def test_id_regex_accepts_T_pattern(self) -> None:
        """T-YYYYMMDD-slug pattern is accepted by the id validator."""
        fm = TaskFrontmatter(
            id="T-20260424-my-task",
            title="x",
            status="ready",
            effort="M",
            budget_usd=1.5,
            agent="dev",
            depends_on=[],
            touches_paths=[],
        )
        assert fm.id == "T-20260424-my-task"

    def test_id_regex_accepts_pN_pattern(self) -> None:
        """pN-slug pattern (e.g. p0-contracts) is accepted by the id validator."""
        fm = TaskFrontmatter(
            id="p0-contracts",
            title="x",
            status="ready",
            effort="M",
            budget_usd=0,
            agent="dev",
            depends_on=[],
            touches_paths=[],
        )
        assert fm.id == "p0-contracts"

    def test_id_regex_rejects_garbage(self) -> None:
        """Arbitrary garbage strings are rejected by the id validator."""
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="BAD_ID",
                title="x",
                status="ready",
                effort="S",
                budget_usd=0,
                agent="dev",
                depends_on=[],
                touches_paths=[],
            )

    def test_extra_fields_ignored(self, tmp_path: Path) -> None:
        """Unknown extra fields in the frontmatter do not raise an error (extra='ignore')."""
        md_with_extras = (
            "---\n"
            "id: p2-extra-fields\n"
            "title: Extra Field Test\n"
            "status: ready\n"
            "effort: S\n"
            "budget_usd: 0\n"
            "agent: dev\n"
            "depends_on: []\n"
            "touches_paths: []\n"
            "future_field_xyz: some_value\n"
            "---\n"
        )
        doc = tmp_path / "extras.md"
        doc.write_text(md_with_extras, encoding="utf-8")
        fm = parse_task_doc(doc)
        assert fm is not None
        assert fm.id == "p2-extra-fields"

    def test_datetime_offset_without_colon_normalised(self) -> None:
        """created field with -0300 offset (no colon) parses to same instant as -03:00."""
        fm_no_colon = TaskFrontmatter(
            id="p3-tz-test",
            title="x",
            status="ready",
            effort="S",
            budget_usd=0,
            agent="dev",
            depends_on=[],
            touches_paths=[],
            created="2026-04-24T16:30:00-0300",  # type: ignore[arg-type]
        )
        fm_with_colon = TaskFrontmatter(
            id="p3-tz-test",
            title="x",
            status="ready",
            effort="S",
            budget_usd=0,
            agent="dev",
            depends_on=[],
            touches_paths=[],
            created="2026-04-24T16:30:00-03:00",  # type: ignore[arg-type]
        )
        assert fm_no_colon.created == fm_with_colon.created


# ---------------------------------------------------------------------------
# Group B — ReadyList JSON (Contract 2)
# ---------------------------------------------------------------------------


class TestReadyList:
    """Contract 2: ReadyList JSON written by anthive scan."""

    def test_loads_example_json(self) -> None:
        """ready_list.example.json parses via ReadyList.model_validate without error."""
        with (CONTRACTS / "ready_list.example.json").open(encoding="utf-8") as fh:
            data = json.load(fh)
        rl = ReadyList.model_validate(data)
        assert rl is not None
        assert len(rl.ready) == 1
        assert rl.ready[0].id == "T-20260424-card-violator-fix"
        assert len(rl.blocked) == 1
        assert len(rl.in_progress) == 1
        assert len(rl.done) == 1
        assert len(rl.conflicts) == 1

    def test_round_trip_json(self) -> None:
        """model_dump_json then model_validate produces an equivalent ReadyList."""
        with (CONTRACTS / "ready_list.example.json").open(encoding="utf-8") as fh:
            data = json.load(fh)
        original = ReadyList.model_validate(data)
        serialised = original.model_dump_json()
        restored = ReadyList.model_validate_json(serialised)
        assert restored.repo_root == original.repo_root
        assert restored.ready[0].id == original.ready[0].id
        assert restored.done[0].merged_at == original.done[0].merged_at
        assert restored.conflicts[0].note == original.conflicts[0].note

    def test_minimal_ready_list_defaults(self) -> None:
        """A ReadyList built with only required fields has empty lists for optional ones."""
        rl = ReadyList(
            scanned_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            repo_root="/tmp/repo",
            tasks_dir="tasks/",
        )
        assert rl.ready == []
        assert rl.blocked == []
        assert rl.in_progress == []
        assert rl.done == []
        assert rl.conflicts == []


# ---------------------------------------------------------------------------
# Group C — SessionLogFrontmatter (Contract 3)
# ---------------------------------------------------------------------------


class TestSessionLogFrontmatter:
    """Contract 3: SessionLogFrontmatter parsed from session log YAML frontmatter."""

    def test_parses_example_session_log(self) -> None:
        """session_log.example.md parses without error."""
        fm = parse_session_log(CONTRACTS / "session_log.example.md")
        assert fm.session_id == "s5-card-violator-fix"
        assert fm.slug == "card-violator-fix"
        assert fm.status == "COOKING"

    def test_parses_reference_template_with_placeholders(self) -> None:
        """Reference template with {{NOW}} placeholders parses; datetime fields are epoch."""
        fm = parse_session_log(REF_LOGS / "session_log_template.md")
        assert fm.status == "INIT"
        assert fm.created == _EPOCH
        assert fm.last_heartbeat == _EPOCH

    def test_write_then_parse_round_trip(self, tmp_path: Path) -> None:
        """write_session_log then parse_session_log preserves all field values."""
        original = SessionLogFrontmatter(
            session_id="s99-round-trip",
            slug="round-trip",
            branch="session/s99-round-trip",
            worktree="worktrees/s99-round-trip",
            container="swarm-s99",
            forked_from_sha="deadbeef1234",
            created="2026-04-24T17:00:00Z",  # type: ignore[arg-type]
            status="COOKING",
            last_heartbeat="2026-04-24T17:05:00Z",  # type: ignore[arg-type]
            last_note="round-trip test",
            task_id="T-20260424-round-trip",
            primary_agent="python-developer",
            budget_usd=1.0,
            spent_usd=0.25,
            tokens_in=500,
            tokens_out=150,
            touches_paths=["src/foo.py"],
            exit_check="tests green",
        )
        log_path = tmp_path / "s99.md"
        write_session_log(log_path, original, "## Body\n\nsome notes\n")
        restored = parse_session_log(log_path)

        assert restored.session_id == original.session_id
        assert restored.slug == original.slug
        assert restored.status == original.status
        assert restored.spent_usd == original.spent_usd
        assert restored.tokens_in == original.tokens_in
        assert restored.tokens_out == original.tokens_out
        assert restored.touches_paths == original.touches_paths
        assert restored.exit_check == original.exit_check

    def test_invalid_status_raises_validation_error(self) -> None:
        """An unrecognised status value triggers a ValidationError."""
        with pytest.raises(ValidationError):
            SessionLogFrontmatter(
                session_id="s1",
                slug="x",
                branch="session/x",
                worktree="worktrees/x",
                container="c1",
                forked_from_sha="abc",
                created="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
                status="RUNNING",  # type: ignore[arg-type]
                last_heartbeat="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
                last_note="x",
            )

    def test_optional_fields_have_sensible_defaults(self) -> None:
        """Numeric counters default to 0, string fields to empty string."""
        fm = SessionLogFrontmatter(
            session_id="s1",
            slug="x",
            branch="session/x",
            worktree="worktrees/x",
            container="c1",
            forked_from_sha="abc",
            created="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            status="INIT",
            last_heartbeat="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            last_note="scaffolded",
        )
        assert fm.spent_usd == 0
        assert fm.tokens_in == 0
        assert fm.tokens_out == 0
        assert fm.budget_usd == 0
        assert fm.touches_paths == []
        assert fm.secondary_agents == []
        assert fm.exit_check == ""
        assert fm.pr_url == ""

    def test_model_field_is_optional(self) -> None:
        """model field is optional and defaults to None."""
        fm = SessionLogFrontmatter(
            session_id="s1",
            slug="x",
            branch="session/x",
            worktree="worktrees/x",
            container="c1",
            forked_from_sha="abc",
            created="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            status="INIT",
            last_heartbeat="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            last_note="scaffolded",
        )
        assert fm.model is None

    def test_last_heartbeat_placeholder_returns_sentinel(self, tmp_path: Path) -> None:
        """A file with last_heartbeat: {{HEARTBEAT}} placeholder returns epoch, not a crash."""
        md = (
            "---\n"
            "session_id: s-placeholder\n"
            "slug: placeholder\n"
            "branch: session/placeholder\n"
            "worktree: worktrees/placeholder\n"
            "container: c1\n"
            "forked_from_sha: abc\n"
            "created: {{NOW}}\n"
            "status: INIT\n"
            "last_heartbeat: {{HEARTBEAT}}\n"
            "last_note: scaffolded\n"
            "---\n"
        )
        doc = tmp_path / "placeholder.md"
        doc.write_text(md, encoding="utf-8")
        fm = parse_session_log(doc)
        assert fm.last_heartbeat == _EPOCH


# ---------------------------------------------------------------------------
# Group D — MergeQueueRow (Contract 4)
# ---------------------------------------------------------------------------


class TestMergeQueueRow:
    """Contract 4: MergeQueueRow parsed from merge-queue markdown bullet lines."""

    def test_parse_example_file_returns_three_rows(self) -> None:
        """merge_queue.example.md contains 3 rows: 2 open + 1 merged."""
        rows = parse_merge_queue(CONTRACTS / "merge_queue.example.md")
        assert len(rows) == 3

    def test_parse_reference_merge_queue_returns_two_rows(self) -> None:
        """Reference merge-queue.md returns 2 open rows (s4 and s3), no merged rows."""
        rows = parse_merge_queue(REF_LOGS / "merge-queue.md")
        assert len(rows) == 2
        session_names = {r.session_name for r in rows}
        assert "s4-self-healing-loop" in session_names
        assert "s3-bird-pilot-ingest" in session_names

    def test_reference_rows_have_no_spent_or_langfuse(self) -> None:
        """Reference rows without spent/langfuse fields parse with those fields as None."""
        rows = parse_merge_queue(REF_LOGS / "merge-queue.md")
        for row in rows:
            assert row.spent_usd is None
            assert row.langfuse is None

    def test_merged_row_has_merged_true(self) -> None:
        """The [x] checkbox row in the example file parses with merged=True."""
        rows = parse_merge_queue(CONTRACTS / "merge_queue.example.md")
        merged_rows = [r for r in rows if r.merged]
        assert len(merged_rows) == 1
        assert merged_rows[0].session_name == "s4-self-healing-loop"

    def test_depends_on_none_yields_empty_list(self) -> None:
        """depends-on: none (without qualifiers) parses to an empty list."""
        rows = parse_merge_queue(CONTRACTS / "merge_queue.example.md")
        # s5-card-violator-fix row: depends-on: none
        s5 = next(r for r in rows if r.session_name == "s5-card-violator-fix")
        assert s5.depends_on == []

    def test_depends_on_session_slug_parsed_correctly(self) -> None:
        """depends-on: s5-card-violator-fix parses to a list with one element."""
        rows = parse_merge_queue(CONTRACTS / "merge_queue.example.md")
        s6 = next(r for r in rows if r.session_name == "s6-heldout-synth")
        assert s6.depends_on == ["s5-card-violator-fix"]

    def test_depends_on_none_with_parenthetical_yields_empty_list(self) -> None:
        """depends-on: none (parenthetical note) is treated as no dependencies."""
        rows = parse_merge_queue(REF_LOGS / "merge-queue.md")
        s4 = next(r for r in rows if r.session_name == "s4-self-healing-loop")
        assert s4.depends_on == []

    def test_round_trip_via_append_and_parse(self, tmp_path: Path) -> None:
        """append_merge_queue_row then parse_merge_queue returns an equivalent row."""
        queue_file = tmp_path / "merge-queue.md"
        original = MergeQueueRow(
            merged=False,
            session_name="s99-test-session",
            pr="PR #99",
            touches=["src/foo.py", "src/bar.py"],
            depends_on=["s98-prev"],
            exit_check="all tests green",
            spent_usd=0.42,
            langfuse="trace-abc-123",
        )
        append_merge_queue_row(queue_file, original)
        rows = parse_merge_queue(queue_file)
        assert len(rows) == 1
        restored = rows[0]
        assert restored.merged == original.merged
        assert restored.session_name == original.session_name
        assert restored.touches == original.touches
        assert restored.depends_on == original.depends_on
        assert restored.exit_check == original.exit_check
        assert restored.spent_usd == pytest.approx(original.spent_usd)
        assert restored.langfuse == original.langfuse

    def test_append_merge_queue_row_is_parseable(self, tmp_path: Path) -> None:
        """A row appended to an existing file is parseable after append."""
        queue_file = tmp_path / "queue.md"
        # Pre-populate with a header so the file is non-empty
        queue_file.write_text("# Merge Queue\n\n## Open\n\n", encoding="utf-8")
        row = MergeQueueRow(
            merged=False,
            session_name="s10-new-feature",
            pr="PR #10",
            touches=["src/module.py"],
            depends_on=[],
            exit_check="smoke tests pass",
        )
        append_merge_queue_row(queue_file, row)
        rows = parse_merge_queue(queue_file)
        assert any(r.session_name == "s10-new-feature" for r in rows)

    def test_spent_usd_parsed_from_example(self) -> None:
        """spent_usd is correctly parsed as a float from the $-prefixed example value."""
        rows = parse_merge_queue(CONTRACTS / "merge_queue.example.md")
        s5 = next(r for r in rows if r.session_name == "s5-card-violator-fix")
        assert s5.spent_usd == pytest.approx(0.08)


# ---------------------------------------------------------------------------
# Group E — Helpers and edge cases
# ---------------------------------------------------------------------------


class TestHelpersAndEdgeCases:
    """Edge cases and helper function tests."""

    def test_split_frontmatter_no_block_returns_empty_dict(self) -> None:
        """_split_frontmatter returns ({}, text) when no frontmatter block is present."""
        text = "# Just a markdown file\n\nNo frontmatter here.\n"
        data, body = _split_frontmatter(text)
        assert data == {}
        assert "Just a markdown" in body

    def test_parse_task_doc_returns_none_for_no_frontmatter(self, tmp_path: Path) -> None:
        """parse_task_doc returns None for a markdown file without frontmatter."""
        doc = tmp_path / "no_fm.md"
        doc.write_text("# Just a title\n\nNo YAML here.\n", encoding="utf-8")
        result = parse_task_doc(doc)
        assert result is None

    def test_split_frontmatter_body_content_preserved(self) -> None:
        """_split_frontmatter preserves body text that follows the closing delimiter."""
        text = "---\nkey: value\n---\n\n# Body heading\n\nBody paragraph.\n"
        data, body = _split_frontmatter(text)
        assert data == {"key": "value"}
        assert "Body heading" in body

    def test_split_frontmatter_quotes_jinja_placeholders(self) -> None:
        """_split_frontmatter converts {{PLACEHOLDER}} tokens so PyYAML parses them."""
        text = "---\ncreated: {{NOW}}\nstatus: INIT\n---\n"
        data, _ = _split_frontmatter(text)
        # After quoting, PyYAML stores the placeholder as a plain string
        assert data["created"] == "{{NOW}}"
        assert data["status"] == "INIT"

    def test_session_log_all_valid_statuses_accepted(self) -> None:
        """All six valid SessionLogFrontmatter statuses parse without error."""
        valid_statuses = [
            "INIT", "COOKING", "CHECKPOINT", "READY-TO-MERGE", "MERGED", "BLOCKED"
        ]
        for status in valid_statuses:
            fm = SessionLogFrontmatter(
                session_id="s1",
                slug="x",
                branch="session/x",
                worktree="worktrees/x",
                container="c1",
                forked_from_sha="abc",
                created="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                last_heartbeat="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
                last_note="test",
            )
            assert fm.status == status

    def test_serialize_merge_queue_row_no_spent_no_langfuse(self) -> None:
        """serialize_merge_queue_row omits spent/langfuse segments when they are None."""
        row = MergeQueueRow(
            merged=False,
            session_name="s1-lean",
            pr="PR #1",
            touches=["src/a.py"],
            depends_on=[],
            exit_check="tests pass",
            spent_usd=None,
            langfuse=None,
        )
        line = serialize_merge_queue_row(row)
        assert "spent" not in line
        assert "langfuse" not in line
        assert "s1-lean" in line

    def test_task_frontmatter_all_valid_statuses_accepted(self) -> None:
        """All four valid TaskFrontmatter statuses parse without error."""
        valid_statuses = ["ready", "blocked", "in_progress", "done"]
        for status in valid_statuses:
            fm = TaskFrontmatter(
                id="p1-status-test",
                title="x",
                status=status,  # type: ignore[arg-type]
                effort="S",
                budget_usd=0,
                agent="dev",
                depends_on=[],
                touches_paths=[],
            )
            assert fm.status == status

    def test_task_frontmatter_all_valid_efforts_accepted(self) -> None:
        """All five effort levels (XS, S, M, L, XL) parse without error."""
        for effort in ["XS", "S", "M", "L", "XL"]:
            fm = TaskFrontmatter(
                id="p1-effort-test",
                title="x",
                status="ready",
                effort=effort,  # type: ignore[arg-type]
                budget_usd=0,
                agent="dev",
                depends_on=[],
                touches_paths=[],
            )
            assert fm.effort == effort
