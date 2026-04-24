# SETUP.md — Where to Start

> **If you're a fresh Claude Code session opened in this repo and told "build anthive," start here.**

---

## 0. Orientation (read, then stop and think)

anthive is **already planned**. Nothing has been implemented yet. Your job is to build M1 (the local MVP) by following a pre-written sequence of 6 buildable tasks (`p0.md` → `p5.md`).

Read these in order, once:

1. `README.md` — what anthive is, at the product level
2. `CLAUDE.md` — conventions for working in this repo
3. `tasks/PLAN.md` — the master plan (long, ~483 lines; read it all)
4. `tasks/README.md` — navigation guide to the p*.md files
5. `EXTRACTION_AUDIT.md` — what moved from the ACT repo and why (optional context)

Then come back here for the build-start instructions.

---

## 1. Verify environment

```bash
# Python version
python --version   # must be 3.11+

# Claude Code CLI
claude --version   # any recent version

# tmux (local dispatcher depends on it)
tmux -V

# Docker (optional — only if you want Langfuse working immediately)
docker info >/dev/null 2>&1 && echo "docker ok" || echo "docker missing"

# Git version
git --version      # 2.20+ for worktrees
```

If anything's missing, install before proceeding.

---

## 2. Sanity-check the repo state

```bash
# Expected structure
ls
# → CLAUDE.md  EXTRACTION_AUDIT.md  LICENSE  README.md  SETUP.md
# → anthive/  .claude/  docker/  examples/  pyproject.toml  scripts/
# → swarm.toml  tasks/

# Plan files
ls tasks/
# → PLAN.md  README.md  p0.md  p1.md  p2.md  p3.md  p4.md  p5.md  p6.md  p7.md

# Agent ecosystem (intelligence layer)
find .claude/agents -name "*.md" | wc -l
# → 20+ agents available for subagent invocation

# Reference examples from the ACT project
ls examples/reference-logs/
# → ORCHESTRATION.md  PROMPTS.md  README.md  merge-queue.md  session_log_template.md

# Python package skeleton (mostly stubs — p0 fills schemas.py)
ls anthive/
# → __init__.py  cli.py  schemas.py  dispatchers/  tests/
```

If any of this is off, stop and ask the user rather than guessing.

---

## 3. The build order (M1 — ~4-5 hours)

Build in this exact sequence. Each pN.md has its own frontmatter, success criteria, tasks, and exit check. Respect the contract.

| Step | Task file | What you build | Estimated time |
|---|---|---|---|
| 1 | [`tasks/p0.md`](tasks/p0.md) | Pydantic schemas for all 4 contracts + example files | ~45 min |
| 2 | [`tasks/p1.md`](tasks/p1.md) | `anthive scan` CLI + scanner module + tests | ~60 min |
| 3 | [`tasks/p2.md`](tasks/p2.md) | `anthive compose` CLI + prompt builder + agent picker | ~75 min |
| 4 | [`tasks/p3.md`](tasks/p3.md) | `anthive dispatch --local` — worktree + tmux + claude CLI | ~60 min |
| 5 | [`tasks/p4.md`](tasks/p4.md) | `anthive watch` + Langfuse/OTEL wiring | ~75 min |
| 6 | [`tasks/p5.md`](tasks/p5.md) | `anthive merge` — PR reconciler | ~45 min |

Total M1: ~6 hours of focused build (including tests).

After M1, optional:
- p6.md — cloud dispatcher (3-4 hrs)
- p7.md — meeting capture (3-4 hrs)

---

## 4. How to use .claude/agents/ specialists

Every pN.md task has a recommended specialist in its `agent:` frontmatter. Invoke via the Agent tool:

```
Use the Agent tool with subagent_type=python-developer to implement
the scanner module per tasks/p1.md.
```

Current universal specialists (all in `.claude/agents/`):

- **python-developer** — building Python modules
- **code-reviewer** — after each module, before commit
- **test-generator** — pytest suites for each module
- **codebase-explorer** — orientation in unfamiliar code
- **prompt-crafter** — writing the prompt template for composer
- **meeting-analyst** — for p7 capture pipeline
- **the-planner** — if architectural changes are needed

---

## 5. Launching the first build

### If you're already in a Claude Code session in this repo

Paste this prompt verbatim:

```
I'm starting M1 implementation of anthive per tasks/PLAN.md.

First action: read SETUP.md, then read tasks/PLAN.md end-to-end, then read
tasks/p0.md in full. After reading all three, confirm in 3-5 bullet points:
- what anthive is
- what M1 contains
- what p0 specifically asks you to build

Then start building p0 — Pydantic schemas for the 4 contracts, example files,
and the pytest suite. Use the python-developer agent via the Agent tool for the
implementation and test-generator for the tests.

When p0's exit check passes (pytest green on all schemas + examples round-trip
through parse→serialize→parse), commit as:
  feat(p0): contract schemas + example artifacts
and move to p1.

Follow the autonomy directive from tasks/p0.md body — fill in missing
task-frontmatter fields, pick sensible defaults, only pause for a genuine
blocker. Heartbeat status in tasks/p0.md frontmatter as you progress
(ready → in_progress → done).
```

### If you're in a terminal launching a fresh session

```bash
cd /Users/luanmorenomaciel/GitHub/anthive
claude
# then paste the prompt above
```

---

## 6. What "done" looks like for each milestone

### M1 done when

- [ ] `pip install -e .` works from repo root
- [ ] `anthive scan` on this repo's own `tasks/` correctly lists p0-p7 as ready tasks (dogfood check)
- [ ] `anthive compose p1-scan --dry-run` produces a prompt structurally identical to `examples/reference-logs/PROMPTS.md` for ACT's s1
- [ ] `anthive dispatch --local p-test` (with a test task) creates a worktree + tmux pane
- [ ] `anthive watch` renders the Rich live dashboard reading from Langfuse
- [ ] `anthive merge` lands a test PR on main correctly
- [ ] All tests green: `pytest anthive/` passes

### M2 done when

- [ ] `anthive dispatch --cloud` creates a real Managed Agents session
- [ ] Files from the cloud container land in a local worktree branch
- [ ] Langfuse dashboard shows mode=cloud session alongside mode=local sessions
- [ ] Budget cap fires correctly when a session exceeds threshold

### M3 done when

- [ ] `anthive capture <transcript.md>` produces `tasks/pending/T-*.md` files
- [ ] `anthive capture --watch` fires on new notes/ files
- [ ] `anthive capture --review` promotes pending → tasks/ via questionary UI

### M4 done when

- [ ] `pip install anthive` works from PyPI
- [ ] `claude plugin install anthive` works from Claude Code's plugin registry
- [ ] GitHub repo public with CI (lint + test) green
- [ ] README has a GIF showing the dashboard in action

---

## 7. Anti-patterns to avoid

- **Don't skip p0.** The contracts are load-bearing. Other units break if schemas are wrong.
- **Don't merge units.** `scanner`, `composer`, `dispatcher`, `monitor`, `merger` stay in separate modules. No cross-imports.
- **Don't custom-count tokens.** Use Claude Code's native OTEL exporter; Langfuse aggregates.
- **Don't assume Max vs API auth.** Detect via presence of `ANTHROPIC_API_KEY` env; default to local/subscription.
- **Don't build a GUI.** TUI (Textual) is allowed only for `anthive watch`. Everything else is Rich + Typer.
- **Don't skip tests.** Each pN.md has explicit test requirements.

---

## 8. If you get stuck

1. Re-read `tasks/PLAN.md` § "Non-negotiables" and "Anti-patterns"
2. Look at `examples/reference-logs/` for how the pattern worked on a real project
3. Use the `codebase-explorer` agent to re-orient
4. If genuinely blocked, update the current pN.md with a `status: blocked` block and ask the user

---

## 9. Commits & PRs

- Commit after each passing pN test suite
- Commit message format: `feat(pN): <one-line summary>`
- Push to a feature branch (`build/m1-local`) and open a PR when M1 is complete
- Squash-merge to `main` after review

---

## The one-sentence launch

**Read PLAN.md, then p0.md, then build.** Everything you need — plan, agents, schemas, tests, examples — is in this repo. No cold start required.
