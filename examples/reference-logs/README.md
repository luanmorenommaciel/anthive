# logs/ — Parallel Session Coordination

> **Purpose:** a shared state surface for 3–4 parallel Claude Code sessions running in isolated git worktrees + Docker containers so the accelerated plan ([../tasks/accelerated-plan.md](../tasks/accelerated-plan.md)) compresses from 10 serial days into ~3 wall-clock days without sessions stepping on each other or losing progress.

**Created:** 2026-04-24. **Scope:** session heartbeat + state + handoff — *not* benchmark results (those live in `results/`).

---

## The core idea in one paragraph

Open one Claude Code session per parallel track. Each session gets (a) a **git worktree** under `worktrees/` so its working tree is isolated from your main checkout, (b) a **Docker container** so compute runs don't fight over CPU/memory on the host, and (c) a **living log file** under `logs/sessions/` so its state survives crashes, context compression, and reboots. No session writes directly to `main` — each session exits via a PR from its branch. A fifth "merge session" reconciles the PRs in order.

---

## Directory layout

```
logs/
├── README.md                    ← this file
├── ORCHESTRATION.md             ← how to start / monitor / finish a session
├── PROMPTS.md                   ← copy-paste prompts for each session (with correct agent pre-selected)
├── sessions/                    ← one living state file per session
│   ├── s1-heldout-synthesis.md
│   ├── s2-card-violation-metric.md
│   ├── s3-bird-pilot-ingest.md
│   ├── s4-self-healing-loop.md
│   └── _template.md             ← template for new sessions
└── merge-queue.md               ← ordered list of PRs ready to merge, populated by sessions as they exit

../worktrees/                    ← sibling of logs/; created by scripts/session_init.sh
├── s1-heldout-synthesis/        ← git worktree, branch session/s1-heldout-synthesis
├── s2-card-violation-metric/
├── s3-bird-pilot-ingest/
└── s4-self-healing-loop/
```

---

## Session lifecycle

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  INIT       │───▶│  COOKING    │───▶│  CHECKPOINT │───▶│  READY-TO-  │───▶│  MERGED     │
│  (script)   │    │  (work)     │    │  (commit)   │    │   MERGE     │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
  worktree +         updates log       git commit         PR open on         main fast-
  log file +         every meaningful   + log appended     session/...        forwards or
  branch +           step; heartbeat    with SHA           branch             merge commit;
  container          every ~10 min                                            session log
                                                                              archived
```

**Status values** (in log frontmatter): `INIT` → `COOKING` → `CHECKPOINT` → `READY-TO-MERGE` → `MERGED` (terminal) or `BLOCKED` (needs human).

---

## Why each component earns its spot

| Component | Failure it prevents |
|---|---|
| Git worktree per session | Editing the same file from two sessions — the classic "what happened to my change" bug |
| Docker container per session | Benchmark runs OOM'ing each other; Python dep drift between tracks |
| Living log file | Session context loss after compaction / crash / reboot — the log is the SSOT for where it was |
| PR-only exit | Silent pushes to `main` that break the accelerated-plan honesty trail |
| Merge queue file | Two sessions both ready-to-merge with conflicts nobody noticed |
| Pre-picked specialist agent per session | Session spending 20 min rediscovering what `benchmark/card_validator.py` does |

---

## The four parallel tracks (D1–D5 of the accelerated plan)

| Session | Track | Worktree | Dominant agent | Primary surface |
|---|---|---|---|---|
| **s1** | Phase 2B — Held-out LLM synthesis | `worktrees/s1-heldout-synthesis/` | `schema-card-author` + `llm-specialist` + `benchmark-harness-engineer` | `benchmark/heldout_generator/`, `docs/heldout_generator_prompt.md`, `benchmark/questions_heldout.yaml` |
| **s2** | Phase 4B Track 1 — CARD_VIOLATION scoreboard | `worktrees/s2-card-violation-metric/` | `llm-evaluator-designer` + `results-analyst` + `test-generator` | `benchmark/card_validator.py`, `benchmark/aggregate_stress.py`, `docs/research.md §8.17.11`, `docs/act-arl-summary.md`, `docs/metrics.md` |
| **s3** | Phase 3 pilot — BIRD ingest + 3 DB ARLs | `worktrees/s3-bird-pilot-ingest/` | `duckdb-specialist` + `schema-card-author` | `data/bird/`, `benchmark/arl_bird_*.py`, `benchmark/reading_layer.py` |
| **s4** | Phase 4B Track 2 — Self-healing loop scaffold | `worktrees/s4-self-healing-loop/` | `llm-specialist` + `benchmark-harness-engineer` + `code-reviewer` | `benchmark/self_healing/`, `scripts/run_shadow_benchmark.sh` |

These four surfaces have zero path overlap, so worktrees merge back cleanly in any order. The paper draft (`docs/research.md`) is explicitly **not** edited by these four — a fifth merge session handles it after all four PRs land.

---

## How a session stays resumable

Every session's log file has two parts:

1. **YAML frontmatter** — machine-parsable current state (status, last heartbeat, worktree path, container name, next-action).
2. **Prose timeline** — append-only human log. Every tool call that matters ends with a one-line append. Every git commit gets a log entry with the SHA.

If a session dies:
- Start a new Claude Code session in the same worktree.
- First command: `cat logs/sessions/s{N}-*.md`.
- The prose timeline + frontmatter tell you exactly where to resume.
- `git log --oneline -5` on the session branch confirms what's committed.

No state lives in memory only. If it's not in the log or in a commit, it didn't happen.

---

## Pointers

- **To start a session:** [ORCHESTRATION.md](ORCHESTRATION.md) § Starting a session (one command).
- **To pick the right prompt:** [PROMPTS.md](PROMPTS.md) — four copy-paste prompts, one per track, with agent directives baked in.
- **To monitor sessions:** [ORCHESTRATION.md](ORCHESTRATION.md) § Monitoring from the host.
- **To merge finished work:** [ORCHESTRATION.md](ORCHESTRATION.md) § The merge session.

---

## Non-negotiables (keep us out of trouble)

- **Never** commit to `main` from inside a session worktree. Every exit is a PR.
- **Never** skip the heartbeat in COOKING state. A session silent for >30 min is presumed stalled.
- **Never** touch another session's worktree. If you think you need to, you need a merge session instead.
- **Never** run the full 100M stress matrix in two sessions at once on the same host — DuckDB + parquet reads will thrash. Coordinate via [merge-queue.md](merge-queue.md).
- **Always** update the log's `status:` frontmatter field when you transition states. Grepping status across sessions is how the human sees the fleet at a glance.
