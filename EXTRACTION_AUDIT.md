# EXTRACTION_AUDIT.md

> Record of what was copied from [agent-context-protocol (ACT)](https://github.com/luanmoreno/agent-context-protocol) → this `anthive` repo, what stayed in ACT, and why. Written 2026-04-24 during extraction.

---

## Why the extraction

`anthive` was designed and planned **inside** the ACT repo under `tasks/agentswarm/` (PLAN.md + p0–p7 + README). The orchestration pattern was proven on ACT first — four parallel Claude Code sessions produced 16 commits + 501 benchmark calls + 22 measured hallucinations in ~90 minutes of wall time, which is exactly the kind of run anthive is built to automate.

Once the plan was solid, two reasons to extract:

1. **anthive is a product, not an ACT feature.** Keeping it under `tasks/agentswarm/` would bury it. A dedicated repo lets it have its own README, its own LICENSE, its own versioning, its own Claude Code plugin story.
2. **anthive needs to ship with an intelligence layer.** A bare CLI without `.claude/agents/` + KB + commands is a CLI with no brain. Bringing the universal subset over makes anthive batteries-included.

---

## Classification matrix

Each `.claude/` asset from ACT was classified into:

- **UNIVERSAL** → copied to anthive (applies to any repo, any task)
- **ACT-SPECIFIC** → stayed in ACT (references ACT's domain, schema, research)
- **BORDERLINE** → decided case-by-case, documented below

### Agents — classification

| Agent | Category | Where | Reason |
|---|---|---|---|
| `code-quality/code-cleaner` | UNIVERSAL | anthive | Generic Python cleanup |
| `code-quality/code-documenter` | UNIVERSAL | anthive | Generic docstring/readme generation |
| `code-quality/code-reviewer` | UNIVERSAL | anthive | Generic code review |
| `dev/codebase-explorer` | UNIVERSAL | anthive | Repo orientation — works on any codebase |
| `dev/meeting-analyst` | UNIVERSAL | anthive | Transcript → tasks; foundation of p7 capture |
| `dev/prompt-crafter` | UNIVERSAL | anthive | Prompt engineering — works for any domain |
| `dev/shell-script-specialist` | UNIVERSAL | anthive | Bash scripting — universal |
| `python/python-developer` | UNIVERSAL | anthive | Core agent for p1-p5 implementation |
| `python/llm-specialist` | ACT-specific | ACT | Tuned for ACT's LLM evaluation work |
| `python/ai-prompt-specialist` | ACT-specific | ACT | Overlaps prompt-crafter but ACT-tuned |
| `test/test-generator` | UNIVERSAL | anthive | pytest test generation |
| `test/data-contracts-engineer` | ACT-specific | ACT | Data-specific |
| `test/data-quality-analyst` | ACT-specific | ACT | Data-specific |
| `workflow/brainstorm-agent` | UNIVERSAL | anthive | SDD-lite workflow |
| `workflow/build-agent` | UNIVERSAL | anthive | SDD-lite workflow |
| `workflow/define-agent` | UNIVERSAL | anthive | SDD-lite workflow |
| `workflow/design-agent` | UNIVERSAL | anthive | SDD-lite workflow |
| `workflow/iterate-agent` | UNIVERSAL | anthive | SDD-lite workflow |
| `workflow/ship-agent` | UNIVERSAL | anthive | SDD-lite workflow |
| `architect/the-planner` | UNIVERSAL | anthive | Generic strategic planning |
| `architect/kb-architect` | UNIVERSAL | anthive | KB scaffolding — works for any project |
| `architect/genai-architect` | BORDERLINE | ACT | Kept in ACT; adoption decision later |
| `architect/lakehouse-architect` | ACT-specific | ACT | Data-heavy domain |
| `architect/medallion-architect` | ACT-specific | ACT | Data-heavy domain |
| `architect/schema-designer` | ACT-specific | ACT | Dimensional modeling — data-heavy |
| `data-engineering/ai-data-engineer` | ACT-specific | ACT | RAG/feature stores |
| `data-engineering/sql-optimizer` | ACT-specific | ACT | SQL-heavy domain |
| `research/*` (all 6) | ACT-specific | ACT | ACT paper research infrastructure |

**Count: 14 universal agents copied; 13 ACT-specific stayed.**

### KB domains — classification

| Domain | Category | Where | Reason |
|---|---|---|---|
| `shared` (anti-patterns etc.) | UNIVERSAL | anthive | Cross-project hygiene |
| `python` | UNIVERSAL | anthive | Language fundamentals |
| `pydantic` | UNIVERSAL | anthive | Used heavily in p0 contracts |
| `testing` | UNIVERSAL | anthive | pytest patterns |
| `prompt-engineering` | UNIVERSAL | anthive | Used in p2 composer |
| `genai` | UNIVERSAL | anthive | LLM general knowledge |
| `_templates` | UNIVERSAL | anthive | KB creation templates |
| `act-protocol` | ACT-specific | ACT | ACT's protocol definition |
| `agent-reading-layer` | ACT-specific | ACT | ARL = ACT's invention |
| `benchmarking` | ACT-specific | ACT | ACT's benchmark framework |
| `research-writing` | ACT-specific | ACT | Paper-writing conventions |
| `duckdb` | ACT-specific | ACT | Data-heavy |
| `lakehouse` | ACT-specific | ACT | Data-heavy |
| `medallion` | ACT-specific | ACT | Data-heavy |
| `data-modeling` | ACT-specific | ACT | Data-heavy |
| `data-quality` | ACT-specific | ACT | Data-heavy |
| `modern-stack` | ACT-specific | ACT | Data-heavy |
| `sql-patterns` | ACT-specific | ACT | Data-heavy |

**Count: 7 universal KB domains copied; 11 ACT-specific stayed.**

### Commands — classification

| Command | Category | Where |
|---|---|---|
| `core/meeting` | UNIVERSAL | anthive |
| `core/memory` | UNIVERSAL | anthive |
| `core/readme-maker` | UNIVERSAL | anthive |
| `core/status` | UNIVERSAL | anthive |
| `core/sync-context` | UNIVERSAL | anthive |
| `workflow/*` (all 7) | UNIVERSAL | anthive |
| `review/review` | UNIVERSAL | anthive |
| `visual-explainer/*` (all 8) | UNIVERSAL | anthive |
| `knowledge/create-kb` | UNIVERSAL | anthive |
| `data-engineering/*` (all 8) | ACT-specific | ACT |

**Count: 25 universal commands copied; 8 ACT-specific stayed.**

---

## Files NOT copied from ACT (intentional omissions)

| File / directory | Reason |
|---|---|
| `benchmark/` | ACT's research code; not orchestration-related |
| `data/` | ACT's parquet datasets |
| `docs/` (all 8 files) | ACT-specific research papers/summaries |
| `tasks/*.md` (except `agentswarm/`) | ACT phase plans, not anthive content |
| `logs/sessions/*.md` | ACT's session history (preserved in examples/ as reference) |
| `presentation/` | ACT's slide deck |
| `results/` | ACT's benchmark results |
| `scripts/` beyond `session_*.sh` | ACT-specific scripts |
| `Makefile` | ACT-specific targets |
| `Dockerfile`, `docker-compose.yml` | ACT's benchmark container |
| `generate/`, `sql/`, `worktrees/` | ACT code + runtime artifacts |
| `.claude/storage/`, `.claude/sdd/` | Session-local state |

---

## Files copied as reference (not production code)

Under `examples/reference-logs/`:

| File | What it is |
|---|---|
| `session_log_template.md` | The template used by `session_init.sh` |
| `README.md` | ACT's logs/ README explaining the coordination protocol |
| `ORCHESTRATION.md` | Operator's manual for today's manual fleet run |
| `PROMPTS.md` | The 4 hand-crafted prompts for ACT's s1-s4 sessions |
| `merge-queue.md` | The actual queue state when ACT's fleet ran |

**Purpose:** these show the real-world pattern anthive is automating. When implementing p2 (compose), reference `PROMPTS.md` to see what the generated prompts should look like. When implementing p4 (watch), reference `ORCHESTRATION.md` for the monitoring protocol.

These are **read-only inputs**, not templates to be modified.

---

## Scripts copied (as starting point for p3 Python port)

Under `scripts/`:

- `session_init.sh` → p3 will port to `anthive/dispatchers/local.py`
- `session_heartbeat.sh` → p4 will port to `anthive/state.py`
- `session_finish.sh` → p5 will port to `anthive/merger.py`

The bash versions stay in the repo as:
1. Immediate fallback if Python port breaks
2. Reference for the port (readable implementation spec)

Once the Python ports pass their test suites and land on main, the bash scripts can be removed or moved to `examples/legacy-scripts/`.

---

## Plan files copied (100%)

All of `tasks/agentswarm/` was copied verbatim to `tasks/`:

- `PLAN.md` (~483 lines, the master plan)
- `README.md` (navigation guide)
- `p0.md` through `p7.md` (~2,400 lines of sequenced buildable tasks)

No modifications. These are the ground truth for what to build.

---

## What was created fresh in anthive (not from ACT)

| File | Purpose |
|---|---|
| `README.md` (the product one) | User-facing README with install, features, quick start |
| `CLAUDE.md` | Conventions for Claude Code sessions working in this repo |
| `SETUP.md` | Getting-started handoff for the first fresh Claude Code session |
| `EXTRACTION_AUDIT.md` | This file |
| `LICENSE` | MIT |
| `pyproject.toml` | Python package config (hatchling, typer, rich, pydantic, etc.) |
| `swarm.toml` | Per-project config template |
| `.env.example` | Env variable template (Langfuse keys, optional API key, Slack) |
| `.gitignore` | Python + anthive runtime artifact ignores |
| `.github/workflows/test.yml` | CI lint + test matrix on py3.11 + py3.12 |
| `docker/langfuse-compose.yml` | One-command self-hosted Langfuse |
| `anthive/__init__.py` | Package marker, version |
| `anthive/cli.py` | Typer app stub (subcommands registered during p1-p7) |
| `anthive/schemas.py` | Stub — populated by p0 |
| `anthive/dispatchers/__init__.py` | Dispatcher package marker |
| `anthive/tests/test_smoke.py` | Smoke test — package imports cleanly |

---

## Verification — what you should see in anthive

After extraction, `find /Users/luanmorenomaciel/GitHub/anthive -type f` should show roughly:

- ~40 `.md` files in `.claude/agents/**`
- ~30 `.md` files in `.claude/kb/**`
- ~25 `.md` files in `.claude/commands/**`
- ~10 `.md` files in `tasks/`
- ~5 files in `examples/reference-logs/`
- ~3 files in `scripts/`
- ~7 Python files in `anthive/`
- ~15 root-level files (README.md, CLAUDE.md, SETUP.md, etc.)

Total: ~135 files. All plan, intelligence, and scaffolding; zero production code yet. **p0 is the first production code — everything to that point is design.**

---

## What anthive does NOT inherit from ACT — and why it matters

anthive is deliberately:
- **Not a research tool.** ACT's benchmark/evaluator infrastructure has zero place here.
- **Not data-heavy.** Lakehouse, medallion, DuckDB agents/KB stay in ACT.
- **Not paper-focused.** Research-writing, results-analyst stay in ACT.
- **Not hallucination-detection specific.** CARD_VIOLATION was a finding in ACT; unrelated to anthive.
- **Not tied to one LLM family.** Phase-1 target is Claude only, but the architecture allows OpenAI/Gemini via M4+ extensions.

anthive's scope: **orchestrate parallel Claude Code sessions with file-system contracts.** Everything else is out of scope.

---

## Going back the other way (reverse dependency note)

Can ACT eventually *use* anthive? **Yes.** The north star: once anthive is installable as a Claude Code plugin, ACT can `pip install anthive` and replace its hand-rolled `scripts/session_*.sh` with `anthive dispatch`. ACT becomes anthive's first reference customer, not its only user.

But this is out of scope for the first few weeks of anthive. Build. Ship. Dogfood on ACT last.

---

## Log

- **2026-04-24 18:30 BRT** — Initial extraction. All universal assets copied, Python package scaffolded, plan files verbatim, reference examples preserved. Fresh git init next.

Subsequent edits to this file will record:
- Corrections (if we misclassified something and move it later)
- New domains added to `.claude/kb/` in anthive
- Plugin-install-specific additions
