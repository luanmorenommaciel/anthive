# agentswarm — Master Plan

> **Product:** a Python CLI that scans task documents, dispatches parallel Claude Code sessions (local or cloud), monitors them with Langfuse-grade observability, and reconciles their PRs — so humans stay in the loop only when it matters.
>
> **Created:** 2026-04-24. **Source project:** Agent Context Protocol (ACT). **Status:** planning. **Working name:** `agentswarm`. **Repo plan:** build inside ACT under `tasks/agentswarm/`, extract to standalone repo in milestone M4.

---

## Vision — one paragraph

`agentswarm` turns **human-authored task documents** into **running autonomous sessions** with **one command**. It reads `tasks/*.md` in any repo, picks the tasks that are ready to execute, spawns Claude Code sessions (either locally in git worktrees on your laptop, or remotely via Anthropic's Managed Agents cloud), monitors every session's cost/tokens/status through Langfuse, and reconciles the resulting PRs when sessions finish. The human stays in the loop only at decision points: approving dispatches, resolving blockers, merging PRs. The goal is to collapse the coordination tax that turns "I have 6 ideas" into "I've typed 6 tickets, copy-pasted 6 prompts, babysat 6 terminals, and merged 6 PRs" — from ~8 hours of attention down to ~30 minutes.

---

## Why this exists — the pain we lived through today

On 2026-04-24 we ran four parallel Claude Code sessions against this repo:

- **s1** — Phase 2B held-out synthesis (LLM-generated questions)
- **s2** — CARD_VIOLATION metric + validator work
- **s3** — BIRD pilot ingest across 3 databases
- **s4** — Self-healing ARL loop scaffold

Four sessions produced **16 commits, 99+ tests green, 3 BIRD databases ingested, 501 benchmark calls, 22 measured hallucinations, 2 PRs** in about 90 minutes of wall time. It was great. It was also **90 minutes of continuous human babysitting** — monitoring 19 dashboard ticks, unblocking sessions, copy-pasting prompts, hand-tuning merge ordering. The orchestration tax scaled with session count: 4 sessions, 4x the attention.

Today's scripts (`scripts/session_init.sh`, `scripts/session_heartbeat.sh`, `scripts/session_finish.sh`) and the `logs/` directory are the proof that the pattern works. `agentswarm` is the product that makes the pattern reusable across any project, with the human attention cost dropping ~18x.

---

## The two modes

### Mode A — Semi-autonomous daily driver (local)

```
┌─────────────────────────────────────────────────────────────────┐
│  Morning, coffee in hand                                        │
│                                                                  │
│  $ swarm scan                                                   │
│    → 6 tasks in tasks/, 4 ready to dispatch                     │
│                                                                  │
│  $ swarm dispatch --all-ready                                   │
│    → 4 worktrees scaffolded, 4 tmux panes launched              │
│    → 4 Claude Code sessions start cooking                       │
│                                                                  │
│  $ swarm watch                                                  │
│    → live dashboard: tokens, cost, state, cells-complete        │
│                                                                  │
│  [you get Slack ping when anything hits BLOCKED or DONE]        │
│                                                                  │
│  $ swarm merge                                                  │
│    → reconciles PRs in dependency order, lands on main          │
└─────────────────────────────────────────────────────────────────┘
```

Billed to: your **Claude Max 20x subscription** (free at the margin within quota). Runs on your laptop.

### Mode B — Speech-to-commit pipeline (the grand vision)

```
  Meeting happens (Krisp captures audio)
                 │
                 ▼
  notes/2026-04-24-standup.md (transcript lands)
                 │
                 ▼
  meeting-analyst agent (existing .claude/agents/ agent)
                 │
                 ▼
  tasks/backlog.md (auto-appended with frontmatter)
                 │
                 ▼
  $ swarm scan → $ swarm dispatch --all-ready
                 │
                 ▼
  Parallel sessions cook (local or cloud)
                 │
                 ▼
  PRs open on GitHub
                 │
                 ▼
  Human reviews, merges, moves on
```

Human in the loop: 3 times per day.

---

## Architecture — the 8 units

Each unit is independently testable and connects to the next via **file-system handoffs** (no function imports between units). Unix-pipe philosophy. Swap any unit, the pipeline keeps working.

```
┌──────────────┐  audio → markdown
│ U1: Krisp    │  EXISTS (external)
│ capture      │
└──────┬───────┘
       │ notes/*.md
       ▼
┌──────────────┐  transcript → tasks
│ U2: meeting- │  EXISTS (.claude/agents/dev/meeting-analyst.md)
│ analyst      │
└──────┬───────┘
       │ tasks/backlog.md rows
       ▼
┌──────────────┐  tasks → ready list
│ U3: scanner  │  NEW · p1.md
│ swarm scan   │
└──────┬───────┘
       │ ready_tasks.json
       ▼
┌──────────────┐  task → prompt + agent
│ U4: composer │  NEW · p2.md
│ swarm compose│
└──────┬───────┘
       │ prompts/<task>.md
       ▼
┌──────────────┐  prompt → worktree + branch + log
│ U5: scaffold │  EXISTS (scripts/session_init.sh → port to Python)
│ swarm init   │
└──────┬───────┘
       │ worktrees/<task>/ + logs/sessions/<task>.md
       ▼
┌──────────────┐  worktree → running Claude Code session
│ U6: dispatcher│ NEW · p3.md (local) + p6.md (cloud)
│ swarm dispatch│
└──────┬───────┘
       │ OTEL spans + log updates
       ▼
┌──────────────┐  sessions → dashboard + Langfuse
│ U7: monitor  │  NEW · p4.md
│ swarm watch  │
└──────┬───────┘
       │ logs/merge-queue.md
       ▼
┌──────────────┐  PRs → merged on main
│ U8: merger   │  NEW · p5.md
│ swarm merge  │
└──────────────┘
```

---

## Cost model — the critical decision

This is the single most important architectural decision in the plan. **Billing path matters more than compute path.**

| Mode | Auth | Billing source | Cost per ACT-sized run | When to use |
|---|---|---|---|---|
| **Local via Claude Max 20x** | OAuth / subscription | Max 20x quota (flat monthly) | **~$0 marginal** within rate cap | Default. Daytime interactive work. |
| **Local via API key** | `ANTHROPIC_API_KEY` | Console credits (pay-per-token) | ~$15/day for ACT-sized workload | Rare. Only if Max cap hit. |
| **Cloud via Managed Agents** | `ANTHROPIC_API_KEY` | Console credits + **$0.08/session-hr** | ~$15/day + $0.64/8hr-day | Overnight. Laptop-free. Beyond Max cap. |

**Hard fact from research (2026-04-24):** Managed Agents cannot authenticate through a Max 20x subscription. It requires a Console API key with separate billing. Source: Anthropic support doc 11145838 — *"If you have an `ANTHROPIC_API_KEY` environment variable set, Claude Code will use this API key for authentication instead of your subscription, resulting in API usage charges rather than using your subscription's included usage."*

### Implication for agentswarm

**Local mode is the default and the hero path.** You already pay for Max 20x; local sessions are functionally free at the margin. Cloud mode is an opt-in upgrade for specific situations (overnight runs, laptop-unavailable, beyond-quota bursts).

```toml
# swarm.toml (per-project config)
[dispatcher]
default = "local"  # local is the default — use Max 20x

[dispatcher.local]
auth = "subscription"  # uses your Claude Code OAuth, bills to Max 20x
worktree_dir = "worktrees/"
tmux_session_prefix = "swarm-"

[dispatcher.cloud]
auth = "api_key"       # ANTHROPIC_API_KEY from env
require_confirm = true # force human go/no-go on cloud dispatch (cost control)
budget_cap_usd = 5.00  # per-session hard cap; swarm kills sessions that exceed
```

---

## Observability — Langfuse + Claude Code's native OTEL

Chosen stack (research-validated 2026-04-24):

```
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code native OTEL                                        │
│  CLAUDE_CODE_ENABLE_TELEMETRY=1                                 │
│  CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1                          │
│                                                                  │
│  Emits spans with: tokens, cost USD, cache hits, duration       │
└────────────────────┬────────────────────────────────────────────┘
                     │ OTLP HTTP
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Langfuse (self-hosted, MIT)                                    │
│  docker compose up → localhost:3000                             │
│                                                                  │
│  Ingests OTEL → groups by session.id → dashboards per session   │
└─────────────────────────────────────────────────────────────────┘
                     ▲
                     │ parent span with lifecycle tags
┌────────────────────┴────────────────────────────────────────────┐
│  agentswarm                                                      │
│  emits ONE parent span per session:                              │
│    session.id, task.id, agent.name, lifecycle.state              │
│    (INIT → COOKING → CHECKPOINT → READY-TO-MERGE → MERGED)       │
│                                                                  │
│  Claude Code's native spans nest under this parent.              │
│  Result: single-pane Langfuse view of cost/tokens/duration for   │
│  all N parallel sessions.                                        │
└─────────────────────────────────────────────────────────────────┘
```

**Zero custom cost-accounting code.** Claude Code already emits tokens + cost USD. Langfuse already aggregates. `agentswarm` adds only the lifecycle span (~20 lines of Python).

### Future: build on top of OTEL data

Since every session emits standardized OTEL spans, future extensions are cheap:
- **Cost-per-feature dashboards** — group spans by task.id or feature label
- **Model-efficacy analytics** — which model gets which task types right?
- **Session-cost predictions** — pre-flight estimate before `swarm dispatch`
- **Anomaly detection** — session burning tokens unusually fast → alert
- **Weekly cost reports** — email/Slack digest from Langfuse's query API

The OTEL layer is the API for all of this. `agentswarm` emits the data; downstream tools consume it.

---

## CLI stack — Typer + Rich + questionary, Textual for watch

Research-validated 2026-04-24. Rationale:

- **Typer** — type-hint-driven subcommands, autogenerated `--help`, shell completion. Scales to `swarm {scan,dispatch,watch,merge,capture}` subcommands.
- **Rich** — styled tables, live dashboards (`rich.live.Live` refresh_per_second=1), progress bars, syntax highlighting for diffs/logs. Handles 90% of the UI.
- **questionary** — prompt_toolkit-backed interactive pickers. The "choose model" / "confirm dispatch" UX plain Rich can't match.
- **Textual** — reserved for `swarm watch` if it grows beyond a redrawing table into a focus-managed TUI (keyboard shortcuts, scrollable panes, tabs).

### Three canonical UI patterns

**Pattern 1 — `swarm status` (static snapshot, Rich Table):**

```
              agentswarm · 4 sessions · $12.40 total
 ┏━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓
 ┃  #  ┃ task           ┃ model   ┃ state      ┃ tokens  ┃ cost    ┃
 ┡━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩
 │  1  │ heldout-synth  │ opus-47 │ COOKING    │  12,430 │ $2.85   │
 │  2  │ card-violator  │ sonnet  │ CHECKPOINT │  34,200 │ $1.10   │
 │  3  │ bird-ingest    │ sonnet  │ READY      │   4,102 │ $0.18   │
 │  4  │ self-healing   │ opus-47 │ READY      │  87,880 │ $8.27   │
 └─────┴────────────────┴─────────┴────────────┴─────────┴─────────┘
```

**Pattern 2 — `swarm watch` (live, 3s redraw, `rich.live.Live`):**

Same table above, but updates every 3 seconds with token rate, spinner on COOKING rows, progress bars for tasks with known step counts. Press `q` to exit, `m` to trigger merge reconciler, `d` to dispatch next ready task.

**Pattern 3 — `swarm dispatch <task>` (interactive picker + confirm, questionary + Rich):**

```
? Task: T-20260424-bird-financial (effort: M, budget: $30)
? Mode:  (use arrows)
❯ local     (Claude Max 20x, ~$0 marginal)
  cloud     (Managed Agents, ~$0.64/hr + tokens)
? Parallelism: 1
? Confirm dispatch? (Y/n)

⠋ scaffolding worktree  ████████░░░ 72%
⠙ launching tmux pane   ██████████░ 90%
✓ sess-bird-financial-1 ready at tmux://swarm-s5
  Follow with: swarm watch --only s5
```

### Accessibility

- `--plain` flag disables ANSI for CI/logging
- Respects `NO_COLOR` env var
- Screen-reader-friendly tables (rich emits semantic structure)

---

## Relationship to existing Anthropic products (prior-art clarity)

This section pre-answers the question every reviewer will ask.

### Why not Claude Code's built-in "Agent Teams"?

[Agent Teams](https://code.claude.com/docs/en/agent-teams) (experimental, v2.1.32+) lets one Claude Code session spawn teammates that coordinate through a shared task list + mailbox. It's well-designed for **research/review style collaboration** where multiple agents explore the same codebase.

It **cannot** do what `agentswarm` needs:

| Capability | Agent Teams | agentswarm |
|---|---|---|
| Worktree per session | ❌ (shared working tree) | ✅ |
| Branch per session → PR per session | ❌ | ✅ |
| Scan human-authored `tasks/*.md` | ❌ (prompt-driven) | ✅ |
| Nested teams | ❌ ("no nested teams") | ✅ (via task deps) |
| Resumable across shell restarts | ❌ ("no session resumption") | ✅ (via logs/) |
| Multiple teams per session | ❌ ("one team per session") | ✅ |
| Cost/observability dashboard | ❌ | ✅ |

**Agent Teams is a complement, not a competitor.** A single `agentswarm` task could dispatch to a session that internally uses Agent Teams for parallel exploration. The two systems compose.

### Why not the Claude Agent SDK's subagents?

[Subagents](https://code.claude.com/docs/en/agent-sdk/subagents) run within a single Claude session and return final messages to the parent. Perfect for in-context delegation, wrong shape for N-parallel-independent-PRs.

But subagents are also **reusable assets** — `.claude/agents/*.md` definitions can be picked up by `agentswarm` as the agent field in task frontmatter. We're leveraging the existing ecosystem, not replacing it.

### Why not Managed Agents as the only path?

Because Managed Agents:
1. Requires a Console API key (can't use Max 20x)
2. Bills pay-per-token ($5–$25/MTok) + $0.08/session-hour
3. ACT's today workload would cost ~$15/day via cloud vs $0 via Max 20x

**Cloud mode is the Tesla. Local mode is the Prius that you already own.** Both are in the plan; local is the default.

### Why not ComposioHQ/agent-orchestrator or other existing OSS?

Researched 2026-04-24. Closest match: ComposioHQ/agent-orchestrator (generates its own task plan). Others (Conductor, claude-squad, Crystal, Worktrunk) solve slices (worktrees, tmux) but none do task-doc scanning or end-to-end observability.

**No existing tool does task-doc scanning + worktree + cost/tokens observability as one system.** That's the gap `agentswarm` fills.

---

## Milestones

### M1 — Local MVP (4–5 hours) — the one on the critical path

Goal: replace today's manual scripts with a coherent CLI. Use on ACT immediately.

Deliverables:
- [p0.md](p0.md) — contracts (frontmatter schema + handoff formats)
- [p1.md](p1.md) — `swarm scan`
- [p2.md](p2.md) — `swarm compose`
- [p3.md](p3.md) — `swarm dispatch --local`
- [p4.md](p4.md) — `swarm watch` + Langfuse wiring
- [p5.md](p5.md) — `swarm merge`

Exit criteria:
1. `pip install -e .` from a local checkout works
2. `swarm scan` on ACT's `tasks/` returns today's ready work correctly
3. `swarm dispatch --local <task>` reproduces today's fleet pattern end-to-end
4. `swarm watch` renders the dashboard with Langfuse-backed cost/token data
5. `swarm merge` lands a PR on main the way today's merge session does

### M2 — Cloud dispatcher (3–4 hours) — after ACT paper ships

Deliverable: [p6.md](p6.md) — `swarm dispatch --cloud` via Managed Agents API

Exit criteria:
1. Separate Console API key + credits configured; subscription + API both work from the same `swarm` CLI
2. `swarm dispatch --cloud <task>` runs a task in Anthropic's cloud, pulls files back, opens a PR
3. Cost is tracked in Langfuse identical to local mode (same OTEL schema)
4. Budget cap enforcement (session auto-kills at configured $ threshold)

### M3 — Capture layer (3–4 hours) — the speech-to-commit finish

Deliverable: [p7.md](p7.md) — `swarm capture`

Exit criteria:
1. File-watcher on `notes/` triggers meeting-analyst agent
2. meeting-analyst writes `tasks/pending/T-*.md` with frontmatter contract
3. `swarm scan` picks up pending tasks, human reviews + moves to `tasks/` proper
4. End-to-end: Krisp transcript → backlog row → dispatched session → PR

### M4 — Extract to standalone repo (2 hours) — open-source moment

- Move `tasks/agentswarm/` contents into new repo `github.com/<you>/agentswarm`
- Package for PyPI
- README with quick-start
- GitHub Actions for test + release
- Public launch

---

## Non-negotiables

### Architecture

- **File-system handoffs between units.** No unit imports another. Unix pipe philosophy.
- **Worktree + branch + PR per session.** Never commit to main from a session.
- **Logs are the SSOT.** If a session crashes, resuming reads its log.
- **Langfuse is the observability contract.** Custom metrics go through OTEL, not side channels.

### Cost safety

- Default dispatcher is **local** (Max 20x). Cloud mode requires explicit `--cloud` flag or config override.
- Cloud mode requires a budget cap (`budget_cap_usd`) before it will dispatch.
- `swarm dispatch --cloud` shows a pre-flight cost estimate and requires confirmation (unless `--yes`).
- Langfuse dashboard shows real-time cost; orchestrator kills sessions that exceed 120% of budget cap.

### Honesty trail

Ported from ACT's discipline:
- Every session's log preserves failed attempts (don't rewrite history)
- Every `swarm dispatch` writes a timestamped decision log to `logs/decisions/`
- `swarm merge` always uses `--no-ff` (merge commits preserve session context)
- Token/cost numbers in reports come from Langfuse, not from estimates

### Accessibility & CI

- `--plain` mode for every command (no ANSI, no TUI)
- `--json` mode for scripting (machine-readable status output)
- Respect `NO_COLOR` env var
- Exit codes: 0 success, 1 failure, 2 blocked-needs-human, 3 budget-exceeded

---

## Anti-patterns (learned from today's fleet run)

| Anti-pattern | Why | Instead |
|---|---|---|
| Session spawns without heartbeating | Stale `INIT` status lies about what's happening | Require heartbeat within 60s of dispatch, fail loudly if missing |
| Monitoring loop without cost cap | 90-min dashboard-watching is a failure mode | Langfuse-driven budget alerts push-notify via Slack |
| Prompts written from scratch per task | Identical tasks get drifting prompts | `swarm compose` generates deterministically from task + agent |
| Merge-in-session | Race conditions with running sessions | Dedicated merge session, queue-based, never concurrent |
| Editing `docs/research.md` from multiple sessions | Merge conflicts on paper drafts | Sessions stage `.patch` files; one writing session applies them |
| Budget exceeded silently | Surprise $50 bill | Budget cap enforced in dispatcher, not post-hoc in reports |
| Claude Agent Teams for CI/CD-style work | No worktrees, no PR model | Use agentswarm; teams are for research/review |

---

## Build order — the 10-minute mental map

```
Day 1 (half-day, 4-5 hrs):
  p0 → p1 → p2 → p3 → p4 → p5
  = M1 complete. swarm CLI working on ACT locally.

Day 2 (half-day, 3-4 hrs, after ACT paper v1 draft):
  p6
  = M2 complete. Cloud mode works.

Day 3 (half-day, 3-4 hrs):
  p7
  = M3 complete. Meeting → commit pipeline live.

Day 4 (2 hrs):
  Extract to standalone repo, PyPI, GitHub.
  = M4 complete. Open-source.
```

Total: **~13 hours across 4 half-days**, spread over however many calendar days makes sense given ACT paper priority.

---

## Success — what "done" looks like

After M1 lands, a day like today looks like this:

```bash
# Morning
swarm scan                    # 6 tasks ready
swarm dispatch --all-ready    # 4 sessions launched (2 blocked on deps)
# → close laptop, go to client meeting

# 2 hours later
swarm status                  # see what landed
swarm merge                   # lands 3 PRs, 1 flagged for review
# → 5 min of human attention total

# End of day
swarm status --week           # weekly cost summary from Langfuse
# → $47 on Max 20x quota (free), $0 on Console (cloud wasn't used)
```

Versus today's reality:
- 90 min of dashboard monitoring
- Manual heartbeating when scripts lagged
- Copy-pasting 4 prompts into 4 terminals
- Tracking cost by eyeballing log file sizes
- Merge session with manual dependency ordering

**The 18x attention reduction is the entire product.**

---

## Related docs

- [README.md](README.md) — reading guide for this plan
- [p0.md](p0.md) through [p7.md](p7.md) — the buildable task specs
- `tasks/accelerated-plan.md` — ACT paper critical path (agentswarm is parallel track, not on paper path)
- `logs/README.md` — today's parallel-session coordination (what `agentswarm` replaces)
- `logs/PROMPTS.md` — the 4 hand-crafted prompts from today (what `swarm compose` will auto-generate)
