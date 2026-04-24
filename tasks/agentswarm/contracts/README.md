# anthive contracts

> The four file-format contracts every unit in the 8-unit architecture
> depends on. Frozen at p0; downstream units (`scan`, `compose`, `dispatch`,
> `watch`, `merge`, `capture`) read or write these formats.
>
> Pydantic models for each live in [`anthive/schemas.py`](../../../anthive/schemas.py).

---

## The four contracts

| # | Contract | Example file | Pydantic model | Producer | Consumer |
|---|---|---|---|---|---|
| 1 | Task frontmatter | [`task.example.md`](task.example.md) | `TaskFrontmatter` | human (or `meeting-analyst`) | `anthive scan` |
| 2 | Ready list | [`ready_list.example.json`](ready_list.example.json) | `ReadyList` | `anthive scan` | `anthive compose` / `dispatch` |
| 3 | Session log | [`session_log.example.md`](session_log.example.md) | `SessionLogFrontmatter` | `anthive dispatch` | `anthive watch` / `merge` |
| 4 | Merge-queue row | [`merge_queue.example.md`](merge_queue.example.md) | `MergeQueueRow` | `anthive dispatch` (on `READY-TO-MERGE`) | `anthive merge` |

All four formats share these properties:

- **Machine-parseable without an LLM** — pure YAML / JSON / regex
- **Human-readable** — clear field names, no opaque IDs
- **Git-diff-friendly** — line-oriented, stable ordering
- **Forward-compatible** — unknown fields are ignored, not rejected

---

## Contract 1 — Task frontmatter

YAML block at the top of every `tasks/**/*.md` doc. The body below the
frontmatter is the **specification** (success criteria, tasks, do-not-touch
list).

### Fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `id` | yes | string | Stable unique ID. Pattern: `T-YYYYMMDD-<slug>` for tasks, `pN-<slug>` for plan items. |
| `title` | yes | string | Human-readable one-liner. |
| `status` | yes | enum | `ready` \| `blocked` \| `in_progress` \| `done` |
| `effort` | yes | enum | `XS` \| `S` \| `M` \| `L` \| `XL` |
| `budget_usd` | yes | float | Pre-flight cost estimate. `0` = uses Max 20x subscription (free at margin). |
| `agent` | yes | string | Must exist at `.claude/agents/**/<name>.md`. |
| `depends_on` | yes | list[str] | Task IDs that must reach `done` before this task is ready. |
| `touches_paths` | yes | list[str] | Paths this task will modify. Used for conflict detection. |
| `source` | no | string | Provenance (e.g. `notes/2026-04-24-standup.md#L47`). |
| `created` | no | datetime | ISO 8601 with timezone. |
| `prefer_model` | no | enum | `opus` \| `sonnet` \| `haiku` |
| `mode` | no | enum | `local` \| `cloud` (overrides config default). |
| `max_turns` | no | int | Cap on agent turns within a session. |
| `tags` | no | list[str] | Free-form labels. |

---

## Contract 2 — Ready list

JSON document emitted by `anthive scan`. Consumed by `compose` and `dispatch`.

### Top-level fields

| Field | Type | Notes |
|---|---|---|
| `scanned_at` | datetime | When the scan ran. |
| `repo_root` | string | Absolute path to the repo. |
| `tasks_dir` | string | Relative path scanned (default `tasks/`). |
| `ready` | list[ReadyListEntry] | Tasks with `status: ready` and all deps satisfied. |
| `blocked` | list[BlockedEntry] | Tasks blocked on unfulfilled deps. |
| `in_progress` | list[InProgressEntry] | Tasks with active sessions. |
| `done` | list[DoneEntry] | Tasks merged on `main`. |
| `conflicts` | list[Conflict] | Pairs of tasks touching the same path. |

`ReadyListEntry` mirrors the relevant `TaskFrontmatter` fields plus the source
`path` (e.g. `tasks/p1.md` or `tasks/backlog.md#B-CARD-VALIDATOR-ALIAS-FIX`).

---

## Contract 3 — Session log frontmatter

YAML block at the top of `logs/sessions/<slug>.md`. Updated by `anthive
dispatch` on state transitions and by the session itself on heartbeat.

### Required fields

`session_id`, `slug`, `branch`, `worktree`, `container`, `forked_from_sha`,
`created`, `status`, `last_heartbeat`, `last_note`.

### Status state machine

```
INIT → COOKING → CHECKPOINT → READY-TO-MERGE → MERGED
                                      ↓
                                   BLOCKED  (terminal until human unblocks)
```

### Optional fields

`task_id`, `name`, `mode` (`local`|`cloud`), `primary_agent`,
`secondary_agents`, `model`, `budget_usd`, `spent_usd`, `tokens_in`,
`tokens_out`, `touches_paths`, `exit_check`, `pr_url`, `langfuse_trace_url`.

### Backward compatibility

The lean reference template at [`examples/reference-logs/session_log_template.md`](../../../examples/reference-logs/session_log_template.md)
uses Jinja-style placeholders (e.g. `{{NOW}}`) for unset datetime fields. The
parser tolerates these by substituting an epoch sentinel, so existing ACT
session logs round-trip cleanly.

---

## Contract 4 — Merge-queue row

A single line in `logs/merge-queue.md`, format:

```
- [ ] <session_name> · PR #<n> · touches: <paths> · depends-on: <none|sN,sN> · exit_check: <one-liner> [· spent: $<usd>] [· langfuse: <trace_id>]
```

### Fields

| Field | Required | Notes |
|---|---|---|
| `merged` | yes | Checkbox state. `[ ]` = open, `[x]` = merged. |
| `session_name` | yes | E.g. `s5-card-violator-fix`. |
| `pr` | no | E.g. `PR #23`. Empty if not yet pushed. |
| `touches` | yes | Comma-separated paths. |
| `depends_on` | yes | Comma-separated session names, or `none`. Trailing parenthetical notes are tolerated. |
| `exit_check` | yes | One-line success condition. |
| `spent_usd` | no | Reported only after Langfuse aggregates. |
| `langfuse` | no | Trace ID. |

The reference [`examples/reference-logs/merge-queue.md`](../../../examples/reference-logs/merge-queue.md)
omits `spent` and `langfuse` for in-flight rows; both fields are optional.

---

## Forward-compatibility rules

- Readers MUST NOT reject documents that contain unknown fields. All Pydantic
  models in `anthive/schemas.py` use `extra="ignore"`.
- Producers SHOULD only emit fields documented here (extensions go through a
  PLAN.md amendment first).
- Field renames are breaking changes. Add a new field, deprecate the old one,
  remove it after one release cycle.
