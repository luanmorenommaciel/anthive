"""Tests for anthive p4 — monitor, LangfuseClient, observability.

Groups:
    A — LangfuseClient (4 tests)
    B — observability (3 tests)
    C — render_fleet_dashboard (5 tests)
    D — check_budget_alert (2 tests)
    E — CLI smoke (2 tests)
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console
from rich.panel import Panel

import anthive.observability as obs_module
from anthive.langfuse_client import ZERO_METRICS, LangfuseClient
from anthive.monitor import check_budget_alert, render_fleet_dashboard
from anthive.schemas import SessionLogFrontmatter, write_session_log

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class FakeLangfuseClient:
    """Duck-typed stand-in for LangfuseClient.

    Accepts a pre-populated metrics dict and an optional set of session IDs
    that should raise RuntimeError to simulate Langfuse failures.
    """

    def __init__(
        self,
        metrics: dict[str, dict] | None = None,
        raise_on: set[str] | None = None,
    ) -> None:
        self._metrics = metrics or {}
        self._raise_on = raise_on or set()

    def get_session_metrics(self, session_id: str) -> dict:
        """Return per-session metrics or raise for simulated failures."""
        if session_id in self._raise_on:
            raise RuntimeError(f"simulated failure for {session_id}")
        return self._metrics.get(
            session_id,
            {
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "duration_s": 0.0,
                "trace_id": None,
                "url": None,
            },
        )

    def is_configured(self) -> bool:
        """Always report as configured for the fake."""
        return True


def _write_session_log(
    sessions_dir: Path,
    session_id: str,
    *,
    status: str = "COOKING",
    task_id: str = "T-20260424-foo",
    last_note: str = "",
    model: str | None = "sonnet",
) -> Path:
    """Write a minimal valid session log under sessions_dir.

    Uses the canonical write_session_log serialiser so parse_session_log
    round-trips correctly.
    """
    slug = session_id.replace("/", "-")
    fm = SessionLogFrontmatter(
        session_id=session_id,
        slug=slug,
        branch=f"session/{slug}",
        worktree=f"worktrees/{slug}",
        container=f"anthive-{slug}",
        forked_from_sha="abc1234",
        created=_EPOCH,
        status=status,  # type: ignore[arg-type]
        last_heartbeat=_EPOCH,
        last_note=last_note,
        task_id=task_id,
        model=model,
    )
    path = sessions_dir / f"{slug}.md"
    write_session_log(path, fm, body="")
    return path


def _capture_panel(panel: Panel, *, width: int = 200) -> str:
    """Render a Rich Panel to plain text and return it."""
    buf = io.StringIO()
    con = Console(file=buf, force_terminal=False, no_color=True, width=width)
    con.print(panel)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Group A — LangfuseClient
# ---------------------------------------------------------------------------


class TestLangfuseClient:
    """Group A: LangfuseClient configuration and error-handling behaviour."""

    def test_is_configured_false_when_keys_missing(self) -> None:
        """is_configured returns False when both keys are None."""
        client = LangfuseClient("http://localhost:3000", public_key=None, secret_key=None)
        assert client.is_configured() is False

    def test_is_configured_true_with_both_keys(self) -> None:
        """is_configured returns True when both keys are non-empty strings."""
        client = LangfuseClient(
            "http://localhost:3000",
            public_key="pk-test",
            secret_key="sk-test",
        )
        assert client.is_configured() is True

    def test_get_session_metrics_returns_zeros_when_not_configured(self) -> None:
        """get_session_metrics returns zero-valued dict when client has no keys."""
        client = LangfuseClient("http://localhost:3000", public_key=None, secret_key=None)
        result = client.get_session_metrics("s-anything")

        assert result["tokens_in"] == 0
        assert result["tokens_out"] == 0
        assert result["cost_usd"] == 0.0
        assert result["duration_s"] == 0.0
        assert result["trace_id"] is None
        assert result["url"] is None

    def test_get_session_metrics_returns_zeros_on_httpx_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_session_metrics swallows httpx errors and returns zeros."""
        client = LangfuseClient(
            "http://localhost:3000",
            public_key="pk-test",
            secret_key="sk-test",
        )

        def _raise(*args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "get", _raise)

        result = client.get_session_metrics("s-fail")

        assert result["tokens_in"] == 0
        assert result["cost_usd"] == 0.0
        assert result["trace_id"] is None
        # Must not propagate the exception.


# ---------------------------------------------------------------------------
# Group B — observability
# ---------------------------------------------------------------------------


class TestObservability:
    """Group B: OTEL tracing init, session_span, and lifecycle event safety."""

    def setup_method(self) -> None:
        """Reset the module-level _initialized flag before each test."""
        obs_module._initialized = False

    def teardown_method(self) -> None:
        """Reset the module-level _initialized flag after each test."""
        obs_module._initialized = False

    def test_init_tracing_is_idempotent(self) -> None:
        """Calling init_tracing twice does not raise; second call is a no-op."""
        # First call — may succeed (real OTLP) or silently fall back.
        obs_module.init_tracing(service_name="test-svc", endpoint="http://localhost:9999/otel")
        # The flag is only set on success.  We accept either True or False here
        # because the exporter may fail to connect in CI.
        first_flag = obs_module._initialized

        # Second call must never raise regardless of first outcome.
        obs_module.init_tracing(service_name="test-svc", endpoint="http://localhost:9999/otel")
        # Flag must not change on the second call.
        assert obs_module._initialized is first_flag

    def test_session_span_works_without_init_tracing(self) -> None:
        """session_span yields a span-like object even without prior init_tracing."""
        assert obs_module._initialized is False  # sanity

        from opentelemetry.trace import Span

        with obs_module.session_span("s1", "T-001", "python-developer", "local") as span:
            # Must yield something with the Span interface (at minimum not crash).
            assert hasattr(span, "add_event")

    def test_emit_lifecycle_event_does_not_crash_outside_span(self) -> None:
        """emit_lifecycle_event is safe with no active span (no-op, no exception)."""
        obs_module.emit_lifecycle_event("s-none", "INIT", "COOKING", note="test")
        # Reaching here means no exception was raised.


# ---------------------------------------------------------------------------
# Group C — render_fleet_dashboard
# ---------------------------------------------------------------------------


class TestRenderFleetDashboard:
    """Group C: render_fleet_dashboard output and filtering behaviour."""

    def test_empty_sessions_dir_yields_panel(self, tmp_path: Path) -> None:
        """render_fleet_dashboard with no session logs returns a Rich Panel."""
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)

        result = render_fleet_dashboard(sessions_dir, FakeLangfuseClient())

        assert isinstance(result, Panel)

    def test_merged_sessions_excluded_from_active_table(self, tmp_path: Path) -> None:
        """MERGED sessions are not rendered in the active table."""
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)

        _write_session_log(sessions_dir, "s1-cooking", status="COOKING")
        _write_session_log(sessions_dir, "s2-checkpoint", status="CHECKPOINT")
        _write_session_log(sessions_dir, "s3-merged", status="MERGED")

        panel = render_fleet_dashboard(sessions_dir, FakeLangfuseClient())
        text = _capture_panel(panel)

        assert "s1-cooking" in text
        assert "s2-checkpoint" in text
        assert "s3-merged" not in text

    def test_only_filter_respects_substring_match(self, tmp_path: Path) -> None:
        """--only renders only sessions whose IDs contain the filter substring."""
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)

        _write_session_log(sessions_dir, "s1-foo", status="COOKING")
        _write_session_log(sessions_dir, "s2-bar", status="COOKING")
        _write_session_log(sessions_dir, "s3-baz", status="COOKING")

        panel = render_fleet_dashboard(
            sessions_dir, FakeLangfuseClient(), only=["s1-foo", "s3-baz"]
        )
        text = _capture_panel(panel)

        assert "s1-foo" in text
        assert "s3-baz" in text
        assert "s2-bar" not in text

    def test_cost_from_langfuse_reflected_in_table(self, tmp_path: Path) -> None:
        """Cost returned by the Langfuse client appears formatted in the table."""
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)

        _write_session_log(sessions_dir, "s1-foo", status="COOKING")

        fake_metrics = {
            "s1-foo": {
                "cost_usd": 1.42,
                "tokens_in": 100,
                "tokens_out": 50,
                "duration_s": 60.0,
                "trace_id": None,
                "url": None,
            }
        }
        panel = render_fleet_dashboard(sessions_dir, FakeLangfuseClient(metrics=fake_metrics))
        text = _capture_panel(panel)

        # monitor.py formats cost as f"${cost_usd:.4f}" → "$1.4200"
        assert "$1.4200" in text

    def test_template_file_is_skipped(self, tmp_path: Path) -> None:
        """_template.md is never parsed or rendered."""
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)

        # Write a _template.md that contains Jinja placeholders (not valid without quoting).
        (sessions_dir / "_template.md").write_text(
            "---\nsession_id: {{SID}}\nstatus: COOKING\n---\n",
            encoding="utf-8",
        )
        _write_session_log(sessions_dir, "real-session", status="COOKING")

        panel = render_fleet_dashboard(sessions_dir, FakeLangfuseClient())
        text = _capture_panel(panel)

        assert "real-session" in text
        # Template placeholder must not appear as a row.
        assert "{{SID}}" not in text


# ---------------------------------------------------------------------------
# Group D — check_budget_alert
# ---------------------------------------------------------------------------


class TestBudgetAlert:
    """Group D: check_budget_alert threshold logic."""

    def test_returns_over_budget_sessions(self, tmp_path: Path) -> None:
        """Sessions whose cost exceeds the threshold appear in the result."""
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)

        _write_session_log(sessions_dir, "s1", status="COOKING")
        _write_session_log(sessions_dir, "s2", status="COOKING")

        fake_metrics = {
            "s1": {
                "cost_usd": 5.50,
                "tokens_in": 0,
                "tokens_out": 0,
                "duration_s": 0.0,
                "trace_id": None,
                "url": None,
            },
            "s2": {
                "cost_usd": 1.20,
                "tokens_in": 0,
                "tokens_out": 0,
                "duration_s": 0.0,
                "trace_id": None,
                "url": None,
            },
        }
        result = check_budget_alert(sessions_dir, FakeLangfuseClient(metrics=fake_metrics), threshold=5.0)

        assert len(result) == 1
        sid, cost = result[0]
        assert sid == "s1"
        assert cost == pytest.approx(5.50)

    def test_empty_when_nothing_exceeds_threshold(self, tmp_path: Path) -> None:
        """No sessions appear when all costs are below the threshold."""
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)

        _write_session_log(sessions_dir, "s1", status="COOKING")
        _write_session_log(sessions_dir, "s2", status="COOKING")

        fake_metrics = {
            "s1": {
                "cost_usd": 5.50,
                "tokens_in": 0,
                "tokens_out": 0,
                "duration_s": 0.0,
                "trace_id": None,
                "url": None,
            },
            "s2": {
                "cost_usd": 1.20,
                "tokens_in": 0,
                "tokens_out": 0,
                "duration_s": 0.0,
                "trace_id": None,
                "url": None,
            },
        }
        result = check_budget_alert(sessions_dir, FakeLangfuseClient(metrics=fake_metrics), threshold=10.0)

        assert result == []


# ---------------------------------------------------------------------------
# Group E — CLI smoke
# ---------------------------------------------------------------------------


class TestCli:
    """Group E: CLI subcommand smoke tests using Typer's test runner."""

    def test_status_json_empty_repo_exits_zero(self, tmp_path: Path) -> None:
        """anthive status --json against a repo with no sessions/ exits 0."""
        from typer.testing import CliRunner

        from anthive.cli import app

        runner = CliRunner()
        # No logs/sessions/ dir — the CLI prints a 'no sessions yet' message.
        result = runner.invoke(app, ["status", "--json", "--repo", str(tmp_path)])

        assert result.exit_code == 0

    def test_status_json_with_sessions_emits_valid_json(self, tmp_path: Path) -> None:
        """anthive status --json emits valid JSON when sessions exist."""
        from typer.testing import CliRunner

        from anthive.cli import app

        # Build a minimal repo with one session log.
        sessions_dir = tmp_path / "logs" / "sessions"
        sessions_dir.mkdir(parents=True)
        _write_session_log(sessions_dir, "s1-alpha", status="COOKING")

        # Provide a minimal swarm.toml so load_config doesn't error.
        (tmp_path / "swarm.toml").write_text(
            "[observability]\nlangfuse_url = 'http://localhost:3000'\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(app, ["status", "--json", "--repo", str(tmp_path)])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["session_id"] == "s1-alpha"
        assert parsed[0]["status"] == "COOKING"

    def test_watch_exits_on_missing_sessions_dir(self, tmp_path: Path) -> None:
        """anthive watch exits cleanly with code 0 when sessions dir is absent."""
        from typer.testing import CliRunner

        from anthive.cli import app

        (tmp_path / "swarm.toml").write_text(
            "[observability]\nlangfuse_url = 'http://localhost:3000'\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(app, ["watch", "--repo", str(tmp_path)])

        # CLI prints 'no sessions yet' and exits 0.
        assert result.exit_code == 0
