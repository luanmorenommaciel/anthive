---
session_id: {{SID}}
slug: {{SLUG}}
name: {{NAME}}
branch: {{BRANCH}}
worktree: {{WORKTREE}}
container: {{CONTAINER}}
forked_from_sha: {{HEAD_SHA}}
created: {{NOW}}
status: INIT
last_heartbeat: {{NOW}}
last_note: "scaffolded"
primary_agent: ""
secondary_agents: []
touches_paths: []
exit_check: ""
pr_url: ""
---

# Session {{NAME}}

**Purpose:** (filled in by the session prompt — see logs/PROMPTS.md block for {{SID}})

**Worktree:** `{{WORKTREE}}` · **Branch:** `{{BRANCH}}` · **Forked from:** `{{HEAD_SHA}}` · **Container:** `{{CONTAINER}}`

---

## Goal

(one paragraph — the session fills this from its prompt's Goal block)

## Success criteria

(copy from the referenced `tasks/phase-*.md` plan; this is what the exit_check verifies)

## Do-not-touch list

- `docs/research.md` (paper — reserved for the writing session)
- `main` branch (exit is via PR only)
- Other sessions' worktrees

---

## Timeline

- **{{NOW}}** · `INIT` · scaffolded by `scripts/session_init.sh`
