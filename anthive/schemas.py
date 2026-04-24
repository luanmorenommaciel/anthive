"""anthive contract schemas.

The four canonical file-system contracts every unit in anthive reads or writes.
See tasks/p0.md for the full specification.

Contract 1 — TaskFrontmatter:
    YAML block at the top of every tasks/*.md doc. Parsed by the scanner,
    consumed by the composer and dispatcher.

Contract 2 — ReadyList:
    JSON written by `anthive scan`. Root object that carries ready/blocked/
    in_progress/done/conflicts lists. Consumed by `anthive compose` and
    `anthive dispatch`.

Contract 3 — SessionLogFrontmatter:
    YAML frontmatter for logs/sessions/<slug>.md. Written by the dispatcher,
    mutated by the monitor, consumed by the merger.  Template files use
    Jinja-style placeholders ({{SID}}, {{NOW}}, …) for unresolved fields;
    parse_session_log converts them to safe sentinel values so the template
    itself round-trips without errors.

Contract 4 — MergeQueueRow:
    Bullet-list rows in logs/merge-queue.md. Appended by the dispatcher when a
    session reaches READY-TO-MERGE, consumed by `anthive merge`.

Forward compatibility: all models use ``extra="ignore"`` so future fields added
by newer anthive versions do not break older readers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

# ---------------------------------------------------------------------------
# Sentinel used when a datetime field holds a Jinja placeholder ({{…}}).
# ---------------------------------------------------------------------------
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_PLACEHOLDER_RE = re.compile(r"^\{\{[^}]+\}\}$")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _coerce_datetime(v: object) -> datetime:
    """Coerce a value to datetime.

    Accepts: datetime (passthrough), Jinja placeholder strings (returns epoch),
    ISO 8601 strings (handles ±HHMM offsets without colon).
    """
    if isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        raise ValueError(f"Expected str or datetime, got {type(v).__name__}")
    if _PLACEHOLDER_RE.match(v):
        return _EPOCH
    # Normalise ±HHMM → ±HH:MM so Python 3.11 fromisoformat handles it.
    normalised = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", v)
    return datetime.fromisoformat(normalised)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter_dict, body).

    Returns ({}, text) when no frontmatter block is present.
    Raises ValueError when an opening ``---`` is found but no closing delimiter.

    Jinja-style placeholders like ``{{NOW}}`` are invalid YAML (parsed as a
    nested mapping with unhashable keys).  We quote them before handing the
    block to PyYAML so the template file itself round-trips without errors.
    Pydantic field validators then convert the quoted strings to epoch datetimes
    where appropriate.
    """
    if not text.startswith("---"):
        return {}, text

    # Find the closing delimiter (must be on its own line, after the opener).
    rest = text[3:]
    # Strip a single newline directly after the opening ---
    if rest.startswith("\n"):
        rest = rest[1:]

    close = rest.find("\n---")
    if close == -1:
        raise ValueError("Malformed frontmatter: opening '---' has no closing '---'")

    raw_yaml = rest[:close]
    body = rest[close + 4:]  # skip '\n---'
    if body.startswith("\n"):
        body = body[1:]

    # Quote bare {{…}} tokens so PyYAML does not try to parse them as mappings.
    # Only replace unquoted occurrences (not already inside quotes).
    safe_yaml = re.sub(r"(:\s*)(\{\{[^}]+\}\})", r'\1"\2"', raw_yaml)

    data = yaml.safe_load(safe_yaml) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Frontmatter YAML root must be a mapping, got {type(data).__name__}")
    return data, body


# ---------------------------------------------------------------------------
# Contract 1 — TaskFrontmatter
# ---------------------------------------------------------------------------

_TASK_ID_RE = re.compile(r"^(T-\d{8}-[a-z0-9-]+|p\d+-[a-z0-9-]+)$")


class TaskFrontmatter(BaseModel):
    """YAML frontmatter for a tasks/*.md task document (Contract 1)."""

    model_config = ConfigDict(extra="ignore")

    # Required
    id: str
    title: str
    status: Literal["ready", "blocked", "in_progress", "done"]
    effort: Literal["XS", "S", "M", "L", "XL"]
    budget_usd: float
    agent: str
    depends_on: list[str]
    touches_paths: list[str]

    # Optional
    source: str | None = None
    created: datetime | None = None
    prefer_model: Literal["opus", "sonnet", "haiku"] | None = None
    mode: Literal["local", "cloud"] | None = None
    max_turns: int | None = None
    tags: list[str] = []

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _TASK_ID_RE.match(v):
            raise ValueError(
                f"Task id {v!r} must match T-YYYYMMDD-slug or pN-slug pattern"
            )
        return v

    @field_validator("created", mode="before")
    @classmethod
    def _coerce_created(cls, v: object) -> datetime | None:
        if v is None:
            return None
        return _coerce_datetime(v)


# ---------------------------------------------------------------------------
# Contract 2 — ReadyList
# ---------------------------------------------------------------------------


class ReadyListEntry(BaseModel):
    """One task ready to be dispatched."""

    model_config = ConfigDict(extra="ignore")

    id: str
    path: str
    title: str
    effort: str
    budget_usd: float
    agent: str
    touches_paths: list[str]
    prefer_model: str | None = None


class BlockedEntry(BaseModel):
    """One task blocked by unmet dependencies."""

    model_config = ConfigDict(extra="ignore")

    id: str
    path: str
    blocked_by: list[str]
    reason: str


class InProgressEntry(BaseModel):
    """One task currently being worked on by a live session."""

    model_config = ConfigDict(extra="ignore")

    id: str
    session_id: str
    started: datetime

    @field_validator("started", mode="before")
    @classmethod
    def _coerce_started(cls, v: object) -> datetime:
        return _coerce_datetime(v)


class DoneEntry(BaseModel):
    """One task already merged."""

    model_config = ConfigDict(extra="ignore")

    id: str
    merged_at: datetime
    pr: int | None = None

    @field_validator("merged_at", mode="before")
    @classmethod
    def _coerce_merged_at(cls, v: object) -> datetime:
        return _coerce_datetime(v)


class Conflict(BaseModel):
    """Two or more tasks that touch overlapping paths."""

    model_config = ConfigDict(extra="ignore")

    task_ids: list[str]
    paths: list[str]
    note: str


class ReadyList(BaseModel):
    """Root object written by ``anthive scan`` (Contract 2)."""

    model_config = ConfigDict(extra="ignore")

    scanned_at: datetime
    repo_root: str
    tasks_dir: str
    ready: list[ReadyListEntry] = []
    blocked: list[BlockedEntry] = []
    in_progress: list[InProgressEntry] = []
    done: list[DoneEntry] = []
    conflicts: list[Conflict] = []

    @field_validator("scanned_at", mode="before")
    @classmethod
    def _coerce_scanned_at(cls, v: object) -> datetime:
        return _coerce_datetime(v)


# ---------------------------------------------------------------------------
# Contract 3 — SessionLogFrontmatter
# ---------------------------------------------------------------------------


class SessionLogFrontmatter(BaseModel):
    """YAML frontmatter for a session log file (Contract 3).

    Datetime fields accept Jinja-style placeholders (``{{NOW}}``, etc.).
    Those placeholders are converted to the UTC epoch sentinel (1970-01-01)
    so the reference template parses without raising validation errors.
    """

    model_config = ConfigDict(extra="ignore")

    # Required in both the reference template and the full p0 spec
    session_id: str
    slug: str
    branch: str
    worktree: str
    container: str
    forked_from_sha: str
    created: datetime
    status: Literal["INIT", "COOKING", "CHECKPOINT", "READY-TO-MERGE", "MERGED", "BLOCKED"]
    last_heartbeat: datetime
    last_note: str

    # Optional — present in the full spec but absent from the lean template
    task_id: str | None = None
    name: str | None = None
    mode: Literal["local", "cloud"] | None = None
    primary_agent: str = ""
    secondary_agents: list[str] = []
    model: str | None = None
    budget_usd: float = 0
    spent_usd: float = 0
    tokens_in: int = 0
    tokens_out: int = 0
    touches_paths: list[str] = []
    exit_check: str = ""
    pr_url: str = ""
    langfuse_trace_url: str = ""

    @field_validator("created", "last_heartbeat", mode="before")
    @classmethod
    def _coerce_dt(cls, v: object) -> datetime:
        return _coerce_datetime(v)


# ---------------------------------------------------------------------------
# Contract 4 — MergeQueueRow
# ---------------------------------------------------------------------------


class MergeQueueRow(BaseModel):
    """One row in the merge-queue markdown file (Contract 4)."""

    model_config = ConfigDict(extra="ignore")

    merged: bool
    session_name: str
    pr: str | None
    touches: list[str]
    depends_on: list[str]
    exit_check: str
    spent_usd: float | None = None
    langfuse: str | None = None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_task_doc(path: Path | str) -> TaskFrontmatter | None:
    """Parse a task markdown file and return its frontmatter; None if absent."""
    text = Path(path).read_text(encoding="utf-8")
    data, _ = _split_frontmatter(text)
    if not data:
        return None
    return TaskFrontmatter.model_validate(data)


def parse_session_log(path: Path | str) -> SessionLogFrontmatter:
    """Parse a session log markdown file and return its frontmatter."""
    text = Path(path).read_text(encoding="utf-8")
    data, _ = _split_frontmatter(text)
    return SessionLogFrontmatter.model_validate(data)


def parse_merge_queue(path: Path | str) -> list[MergeQueueRow]:
    """Parse a merge-queue markdown file and return all valid rows.

    Skips HTML comments (``<!-- ... -->``) including multi-line comment blocks
    that contain example template rows.
    """
    text = Path(path).read_text(encoding="utf-8")
    rows: list[MergeQueueRow] = []
    in_comment = False
    for line in text.splitlines():
        # Track HTML comment blocks (<!-- ... -->)
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        row = _parse_merge_queue_line(line)
        if row is not None:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------


def serialize_merge_queue_row(row: MergeQueueRow) -> str:
    """Serialise a MergeQueueRow to a markdown bullet-list line."""
    checkbox = "[x]" if row.merged else "[ ]"
    touches_part = ", ".join(row.touches) if row.touches else ""
    depends_part = ", ".join(row.depends_on) if row.depends_on else "none"
    line = f"- {checkbox} {row.session_name}"
    if row.pr:
        line += f" · {row.pr}"
    line += f" · touches: {touches_part}"
    line += f" · depends-on: {depends_part}"
    line += f" · exit_check: {row.exit_check}"
    if row.spent_usd is not None:
        line += f" · spent: ${row.spent_usd:.2f}"
    if row.langfuse is not None:
        line += f" · langfuse: {row.langfuse}"
    return line


def write_session_log(path: Path, fm: SessionLogFrontmatter, body: str) -> None:
    """Write a session log file with YAML frontmatter followed by body text."""
    raw = fm.model_dump(mode="json", exclude_none=True)
    # Ensure list fields that default to [] are always present
    for list_field in ("secondary_agents", "touches_paths"):
        if list_field not in raw:
            raw[list_field] = []
    for str_field in ("primary_agent", "exit_check", "pr_url", "langfuse_trace_url"):
        if str_field not in raw:
            raw[str_field] = ""
    yaml_text = yaml.safe_dump(raw, default_flow_style=False, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{yaml_text}---\n{body}", encoding="utf-8")


def append_merge_queue_row(path: Path, row: MergeQueueRow) -> None:
    """Append a merge-queue row to the end of the queue file."""
    line = serialize_merge_queue_row(row)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{line}\n")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_merge_queue_line(line: str) -> MergeQueueRow | None:
    """Parse one bullet line from a merge-queue file.

    Returns None for headers, comments, empty lines, and malformed bullets.
    Handles both the full p0 format (with spent/langfuse) and the leaner
    reference-log format (without those optional fields).
    """
    stripped = line.strip()

    # Skip non-bullet lines, comments, and empty content
    if not stripped.startswith("- "):
        return None
    if stripped.startswith("- <!--") or stripped == "- ":
        return None

    # Must be a checkbox bullet: - [ ] or - [x]
    checkbox_match = re.match(r"^- \[([ xX])\] (.+)$", stripped)
    if not checkbox_match:
        return None

    merged = checkbox_match.group(1).lower() == "x"
    content = checkbox_match.group(2)

    # Split on the ` · ` separator
    parts = [p.strip() for p in content.split(" · ")]
    if len(parts) < 4:
        return None

    session_name = parts[0]

    # Remaining parts are key: value pairs, except that the second part may be
    # a bare PR reference (e.g. "PR #10") without an explicit key label.
    field_map: dict[str, str] = {}
    idx = 1

    # Check whether the second segment is a bare PR reference
    pr_value: str | None = None
    if re.match(r"^PR\s+#\d+$", parts[idx], re.IGNORECASE):
        pr_value = parts[idx]
        idx += 1

    for part in parts[idx:]:
        if ":" in part:
            key, _, value = part.partition(":")
            field_map[key.strip().lower()] = value.strip()

    # touches
    raw_touches = field_map.get("touches", "")
    touches = [t.strip() for t in raw_touches.split(",") if t.strip()] if raw_touches else []

    # depends-on
    # Values like "none (parenthetical note)" are treated as empty (no deps).
    raw_depends = field_map.get("depends-on", "none").strip()
    depends_on: list[str] = []
    if raw_depends and not raw_depends.lower().startswith("none"):
        depends_on = [d.strip() for d in raw_depends.split(",") if d.strip()]

    # exit_check — key may appear as "exit_check" or "exit check"
    exit_check = field_map.get("exit_check", field_map.get("exit check", ""))

    # spent_usd
    spent_usd: float | None = None
    raw_spent = field_map.get("spent", None)
    if raw_spent is not None:
        try:
            spent_usd = float(raw_spent.lstrip("$"))
        except ValueError:
            pass

    # langfuse
    langfuse = field_map.get("langfuse", None) or None

    return MergeQueueRow(
        merged=merged,
        session_name=session_name,
        pr=pr_value,
        touches=touches,
        depends_on=depends_on,
        exit_check=exit_check,
        spent_usd=spent_usd,
        langfuse=langfuse,
    )
