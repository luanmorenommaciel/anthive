# CLAUDE.md — Project Context for Claude Code Sessions

> **You are working in the `anthive` repo.** This file tells you what anthive is, what conventions it follows, and how to contribute to it without breaking the design.

---

## What is anthive?

A Python CLI + Claude Code plugin that orchestrates parallel Claude Code sessions. It:
1. Scans a repo's `tasks/` directory for task docs
2. Composes a deterministic prompt per task
3. Dispatches sessions (local tmux + claude CLI, or cloud via Managed Agents)
4. Monitors via Langfuse + OTEL
5. Reconciles PRs in dependency order
6. Optionally captures meeting transcripts into the backlog

Born from the real parallel-session pattern proved in the [Agent Context Protocol](https://github.com/luanmoreno/agent-context-protocol) project. Read `examples/reference-logs/` to see how it actually runs.

---

## Where to start reading

**If you're implementing anthive for the first time:**
1. Read [`SETUP.md`](SETUP.md) — the build handoff doc (tells you exactly where to begin)
2. Read [`tasks/PLAN.md`](tasks/PLAN.md) top to bottom — the master plan
3. Read [`tasks/README.md`](tasks/README.md) — navigation guide
4. Start at [`tasks/p0.md`](tasks/p0.md) — contracts (must be done first)

**If you're resuming implementation:**
- Check `git log --oneline -20` for latest work
- Check `tasks/p*.md` `status:` frontmatter fields for what's done
- Run `pytest` to see which modules are green

---

## Conventions

### Code style

- **Python 3.11+** (match `pyproject.toml`)
- **Type hints everywhere** (Pydantic models for external data, dataclasses for internal)
- **No runtime deps we don't need** — current list: `typer`, `rich`, `questionary`, `pydantic`, `pyyaml`, `watchdog`, `httpx`, `opentelemetry-*`, `anthropic` (cloud only)
- **Tests via `pytest`** in `anthive/tests/` next to each module
- **Ruff for linting**, **black for formatting** (wire up in pyproject.toml)

### File-system handoffs, not imports

`anthive` is 8 logical units connected by file-system contracts. **Units do not import each other.** They read and write files whose format is defined in [`tasks/p0.md`](tasks/p0.md).

- `scanner` reads `tasks/*.md`, writes a `ReadyList` (JSON)
- `composer` reads `ReadyList`, writes `prompts/<task-id>.md`
- `dispatcher` reads `prompts/<task-id>.md`, writes `logs/sessions/<slug>.md` + launches tmux/cloud session
- etc.

This isolation is intentional: any unit can be swapped, tested alone, or replaced by a shell script.

### Pydantic contracts

Every file-system artifact has a Pydantic model in `anthive/schemas.py`. Parsers/serializers round-trip cleanly (parse → serialize → parse is idempotent). See [`tasks/p0.md`](tasks/p0.md) for the four canonical schemas.

### Agent delegation

Use `.claude/agents/` specialists via the Agent tool:
- `python-developer` — building Python modules
- `code-reviewer` — before finalizing a PR
- `test-generator` — after building a module
- `codebase-explorer` — orientation in unfamiliar code
- `prompt-crafter` — when writing new prompts for the composer
- `the-planner` — when adjusting the overall plan

---

## Observability rules

- **Don't invent cost tracking.** Claude Code's native OTEL exporter emits tokens + cost USD already. anthive emits *one parent lifecycle span* per session and lets Claude Code spans nest under it.
- **Langfuse is the backend.** Self-hosted by default (`docker/langfuse-compose.yml`). Queries via `anthive/langfuse_client.py`.
- **OTEL env vars must be set by the dispatcher** before launching the child process:
  - `CLAUDE_CODE_ENABLE_TELEMETRY=1`
  - `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:3000/api/public/otel`
  - `OTEL_RESOURCE_ATTRIBUTES=session.id=<sid>,task.id=<tid>,agent=<agent>`

---

## CLI aesthetic

Stack: **Typer + Rich + questionary**, with Textual reserved for `anthive watch` if it grows.

Required for every command:
- `--json` flag for machine-readable output
- `--plain` flag for ANSI-free CI output
- Respect `NO_COLOR` env var
- Non-zero exit codes: `1` failure, `2` blocked-needs-human, `3` budget-exceeded

---

## Auth model

- **Local mode (default):** uses Claude Code's OAuth / subscription (Claude Max 20x). Zero API credits consumed. Detected by presence of `~/.claude/` OAuth config.
- **Cloud mode (opt-in):** requires `ANTHROPIC_API_KEY` Console API key. Bills Console credits (`$0.08/session-hour` + tokens). Hard-fail with clear error if key is missing.

**Never mix subscription + API key auth in the same session.** If user has both, respect `swarm.toml` config; default to local.

---

## Git model

- **One worktree + one branch + one PR per session.** Never commit to `main` from inside a session worktree.
- **Branch naming:** `session/<slug>`
- **Worktree path:** `worktrees/<slug>/` (gitignored)
- **Exit via PR.** `anthive merge` is the only path to land on main.
- **`--no-ff` merges always.** Preserves session commit graph.
- **Never `--no-verify`.** Respect pre-commit hooks. Fix what they complain about.

---

## Budget safety

Three-layer defense against runaway costs:

1. **Pre-flight estimate.** `anthive dispatch --cloud` shows expected cost, requires confirmation (unless `--yes`).
2. **Per-session cap.** `budget_cap_usd` in task frontmatter or config. Monitor kills session that exceeds 120% of cap.
3. **Daily cap.** `anthive.daily_budget_usd` in config. `dispatch --cloud` refuses if today's spend already exceeds.

If a session hits the cap, transition to `BLOCKED` status and ping the user. Don't silently continue.

---

## Honesty trail (ported from ACT)

Every dispatch records a decision. Every merge records a decision. Every failed attempt stays in the session log. Never rewrite history to make numbers look better.

- Session logs preserve `INIT → COOKING → ... → MERGED` timeline
- Merge decisions go to `logs/decisions/merge-<ts>.md`
- Budget overruns go to `logs/decisions/budget-<ts>.md`
- Failed sessions go to `logs/archive/<date>/<slug>.md` with full history intact

---

## Files you should never modify

- `.claude/agents/` content — these are curated specialists from the parent project (ACT); modifying them changes behavior everywhere
- `examples/reference-logs/` — read-only reference showing the proven pattern
- Task docs with `status: done` or `status: merged` — use `anthive iterate` instead

---

## Files you will modify a lot

- `anthive/**` — the Python package
- `tasks/p*.md` — update `status:` as you progress; add "Actual Results" sections after implementation
- `tasks/PLAN.md` — only for material architecture changes (document the reasoning)
- `pyproject.toml`, `swarm.toml` — config surface
- `docker/langfuse-compose.yml` — if you need to add services

---

## Related docs

- [`README.md`](README.md) — product README (user-facing)
- [`SETUP.md`](SETUP.md) — where a fresh Claude Code session should start
- [`EXTRACTION_AUDIT.md`](EXTRACTION_AUDIT.md) — what was copied from the ACT repo and why
- [`tasks/PLAN.md`](tasks/PLAN.md) — the master plan (2,930 lines, read it once cover-to-cover)

---

## The one-sentence north star

**anthive turns "I have 6 ideas" into 6 PRs with ~30 minutes of human attention instead of 8 hours.** Every decision in this codebase should serve that goal.
