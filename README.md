# anthive

> **A structured swarm for Claude Code.** Turn human-authored task docs into parallel autonomous sessions — local via your Claude Max subscription, or cloud via Anthropic Managed Agents — with end-to-end cost/token observability through Langfuse. Stay in the loop only when it matters.

```
         anthive · 4 sessions · $12.40 total
 ┏━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓
 ┃  #  ┃ task           ┃ model   ┃ state      ┃ tokens  ┃ cost    ┃
 ┡━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩
 │  1  │ refactor-harness│ opus-47 │ COOKING    │  12,430 │ $2.85   │
 │  2  │ add-rate-limit  │ sonnet  │ CHECKPOINT │  34,200 │ $1.10   │
 │  3  │ bird-ingest     │ sonnet  │ READY      │   4,102 │ $0.18   │
 │  4  │ refresh-docs    │ haiku   │ READY      │   8,880 │ $0.27   │
 └─────┴─────────────────┴─────────┴────────────┴─────────┴─────────┘
```

---

## The vision in 30 seconds

1. You write task docs (`tasks/T-*.md`) — human intent, one file per work item
2. `anthive scan` reads them, lists what's ready
3. `anthive dispatch --all-ready` spawns N parallel Claude Code sessions — each in its own git worktree + branch
4. `anthive watch` gives you a live dashboard: tokens, cost, state, progress
5. Sessions open PRs when done; `anthive merge` reconciles them in dependency order

**Goal:** collapse the coordination tax. Six tasks should take 30 minutes of human attention, not 8 hours.

---

## Why anthive exists

Today, running N parallel Claude Code sessions means:
- Copy-pasting N prompts into N terminals
- Babysitting N tmux panes
- Tracking cost by eyeballing log sizes
- Hand-merging PRs in correct dependency order

**anthive is the missing orchestration layer.** It's born from the real-world pattern we proved out on the [Agent Context Protocol](https://github.com/luanmoreno/agent-context-protocol) project, where 4 parallel sessions produced 16 commits + 99 tests + 3 database ingests + 501 benchmark calls in 90 minutes — but 90 minutes of human attention we'd rather not spend again.

## What makes anthive different

| Feature | anthive | Claude Code's "Agent Teams" | ComposioHQ/agent-orchestrator |
|---|---|---|---|
| Worktree + branch per session | ✅ | ❌ shared working tree | ✅ |
| PR-per-session exit model | ✅ | ❌ | ✅ |
| Scan human-authored `tasks/*.md` | ✅ | ❌ prompt-driven | ❌ self-generates tasks |
| Uses Claude Max subscription (free at margin) | ✅ | ✅ | ❌ API key required |
| Cloud dispatch (Managed Agents) | ✅ opt-in | ❌ | ❌ |
| End-to-end observability (Langfuse + OTEL) | ✅ | ❌ | ⚠ partial |
| Meeting-transcript → backlog pipeline | ✅ M3 | ❌ | ❌ |
| Ships as Claude Code plugin | ✅ | N/A | ❌ |

---

## The two modes

### Local mode (default, free at the margin)

Uses your **Claude Max 20x subscription** via Claude Code's OAuth. Every session is a tmux pane running the `claude` CLI. Zero API credits consumed.

```bash
anthive dispatch --local T-20260425-add-rate-limit
# → creates worktrees/add-rate-limit/ + branch session/add-rate-limit
# → launches tmux pane swarm-add-rate-limit with `claude` + the composed prompt
# → session log at logs/sessions/add-rate-limit.md tracks state
```

### Cloud mode (opt-in, pay-as-you-go)

Uses **Anthropic's Managed Agents API** — sessions run in Anthropic-provisioned containers, not your laptop. Requires a Console API key.

- Cost: **$0.08 per session-hour** + standard token pricing (no markup on tokens)
- Use for: overnight runs, laptop-free workflows, bursting past Max quota
- Budget cap enforced per-session

```bash
anthive dispatch --cloud T-20260425-bird-5-dbs --yes
# → creates agent + environment + session via Anthropic API
# → session runs in cloud; files pulled back and committed to local worktree
```

---

## Installation

### As a Python CLI

```bash
pip install anthive
```

### As a Claude Code plugin

```bash
claude plugin install anthive
```

### Prerequisites

- Python 3.11+
- Claude Code CLI installed and authenticated (`claude setup-token` for Max/Pro subscription)
- Git 2.20+ (for worktrees)
- tmux (for local mode)
- Docker (optional, for self-hosted Langfuse)
- Anthropic Console API key (optional, only for cloud mode)

---

## Quick start

```bash
# 1. Initialize config in your project
anthive init

# 2. Author a task
cat > tasks/T-20260425-hello.md <<EOF
---
id: T-20260425-hello
title: "Add a hello-world endpoint"
status: ready
effort: S
agent: python-developer
touches_paths: [src/api/hello.py, tests/test_hello.py]
---

# Add a hello-world endpoint

Success: GET /hello returns {"message": "hello"}. Tests cover the endpoint.
EOF

# 3. Scan
anthive scan
# Shows: 1 ready task

# 4. Dispatch
anthive dispatch T-20260425-hello --yes

# 5. Watch
anthive watch
# Live dashboard with tokens, cost, state

# 6. When READY-TO-MERGE appears
anthive merge
# PR landed on main
```

---

## Architecture

```
┌──────────────┐  audio → markdown
│ Krisp        │  (external tool — Granola, Otter, any transcript source)
└──────┬───────┘
       │ notes/*.md
       ▼
┌──────────────┐  transcript → tasks
│ meeting-     │  (Claude agent — ships with anthive)
│ analyst      │
└──────┬───────┘
       │ tasks/pending/T-*.md
       ▼
┌──────────────┐  tasks → ready list
│ anthive scan │
└──────┬───────┘
       │
       ▼
┌──────────────┐  task → prompt + agent
│ anthive      │
│ compose      │
└──────┬───────┘
       │
       ▼
┌──────────────┐  prompt → running session (local tmux | cloud container)
│ anthive      │
│ dispatch     │
└──────┬───────┘
       │ OTEL spans
       ▼
┌──────────────┐  sessions → dashboard
│ anthive watch│  Rich live UI + Langfuse backend
└──────┬───────┘
       │
       ▼
┌──────────────┐  PRs → merged
│ anthive      │
│ merge        │
└──────────────┘
```

Eight units total, connected by file-system handoffs. See [`tasks/PLAN.md`](tasks/PLAN.md) for the full architecture spec.

---

## Observability — cost, tokens, everything

anthive wires Claude Code's **native OpenTelemetry exporter** into a self-hosted **Langfuse** instance. Every session emits standardized spans carrying tokens, cost USD, cache hits, duration. No custom cost-accounting code.

```bash
# Stand up Langfuse locally (one command)
docker compose -f docker/langfuse-compose.yml up -d

# Dispatch with telemetry (automatic once Langfuse is up)
anthive dispatch T-X
# → Claude Code emits OTEL → Langfuse ingests
# → anthive watch dashboard reads live cost/tokens from Langfuse

# View the traces
open http://localhost:3000
```

Because every session's data is standardized OTEL, downstream analytics are cheap:
- Cost-per-feature dashboards (group by task.id)
- Model-efficacy analytics (which model gets what right?)
- Anomaly detection (session burning tokens unusually fast)
- Weekly cost reports via Langfuse's query API

---

## CLI reference (planned — M1)

```
anthive scan              # What's ready to work on?
anthive compose <task>    # Generate prompt + agent selection for a task
anthive dispatch <task>   # Spawn a session (--local | --cloud)
anthive watch             # Live dashboard
anthive status            # One-shot snapshot
anthive merge             # Reconcile PRs in dependency order
anthive capture <path>    # Transcript → backlog (M3)
anthive init              # Scaffold anthive in a project
```

---

## Build milestones

| Milestone | Content | Status |
|---|---|---|
| **M1 — Local MVP** | scan + compose + dispatch --local + watch + merge | 🟡 in planning |
| **M2 — Cloud** | dispatch --cloud via Managed Agents | ⚪ after M1 |
| **M3 — Capture** | transcript → backlog pipeline | ⚪ after M2 |
| **M4 — Plugin + PyPI** | Claude Code plugin package + public release | ⚪ after M3 |

See [`tasks/PLAN.md`](tasks/PLAN.md) for the full plan and [`tasks/p0.md`](tasks/p0.md) through [`tasks/p7.md`](tasks/p7.md) for sequenced buildable tasks.

---

## Project structure

```
anthive/
├── tasks/              ← PLAN + p0-p7 buildable tasks
├── anthive/            ← Python package
├── .claude/            ← Agents, KB, commands (ships with anthive)
├── examples/           ← Reference session logs from ACT (real-world pattern)
├── docker/             ← Langfuse compose file
├── scripts/            ← session_*.sh (M1 ports these to Python)
├── README.md           ← you are here
├── CLAUDE.md           ← project context for Claude Code sessions
├── SETUP.md            ← getting-started for build sessions
└── EXTRACTION_AUDIT.md ← what moved from the ACT repo and why
```

---

## Philosophy

- **Worktree + branch + PR per session.** Never commit to main from a session.
- **File-system handoffs between units.** No unit imports another. Unix pipe discipline.
- **Human authors intent; agents execute.** Meeting-analyst extracts, humans curate, agents build.
- **Local by default.** Don't burn API credits when your Max subscription is sitting right there.
- **Observability or it didn't happen.** Every session's cost is in Langfuse, not estimated post-hoc.
- **Honest failure.** If a session fails, the log preserves the failure. No rewriting history.

---

## Prior art (why anthive, specifically)

We researched the ecosystem on 2026-04-24:

- **Claude Code's "Agent Teams"** (experimental) — inter-agent messaging, shared task list. Same working tree, no PR model. Complementary, not overlapping.
- **Claude Agent SDK subagents** — in-context delegation. Perfect for focused tasks, wrong shape for N parallel independent PRs.
- **ComposioHQ/agent-orchestrator** — closest match. Self-generates tasks from a single prompt. anthive reads human-authored task docs instead.
- **Conductor, claude-squad, Crystal, Worktrunk** — solve worktrees + tmux slice well. None do task-doc scanning or cost observability.
- **Langfuse, LangSmith, Helicone, Traceloop, Weave** — observability options. Langfuse + Claude Code's native OTEL was the winning combination.

**No existing tool does task-doc scanning + worktree-per-session + end-to-end cost observability.** That's the gap anthive fills.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Status

**Pre-alpha.** Plan is written (~2,930 lines across `tasks/PLAN.md` + p0-p7). M1 implementation starts next. See [`SETUP.md`](SETUP.md) for the getting-started prompt for fresh Claude Code sessions.
