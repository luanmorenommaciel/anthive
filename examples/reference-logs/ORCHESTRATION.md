# Orchestration — Parallel Claude Code Sessions

> How to start, monitor, and finish parallel sessions running on git worktrees + Docker. See [README.md](README.md) for the design rationale.

---

## Prerequisites (one-time, on host)

```bash
# Confirm Docker is running and the image is built
docker info >/dev/null && echo "docker ok"
make docker-build                       # builds the act-benchmark image used by all sessions

# Confirm scripts are executable
chmod +x scripts/session_init.sh scripts/session_heartbeat.sh scripts/session_finish.sh

# Confirm .env exists (OpenRouter keys + optional LangFuse)
ls -la .env && head -5 .env | sed 's/=.*/=***/'
```

---

## Starting a session (copy-paste)

### 1. Host-side setup — run ONCE per session, before opening Claude Code

```bash
# From the main checkout
./scripts/session_init.sh s1 heldout-synthesis
```

This script:
1. Creates git worktree at `worktrees/s1-heldout-synthesis/` on a new branch `session/s1-heldout-synthesis` forked from current HEAD.
2. Initializes `logs/sessions/s1-heldout-synthesis.md` from the template, status `INIT`.
3. Prints the Claude Code launch command (or opens it if the CLI is available).
4. Prints the Docker container name you'll use for this session's compute.

### 2. Open Claude Code in the worktree

```bash
# In a new terminal (or your IDE's Claude Code extension pointed at the worktree)
cd worktrees/s1-heldout-synthesis
claude
```

### 3. Paste the session's prompt

From [PROMPTS.md](PROMPTS.md), copy the block for `s1-heldout-synthesis` and paste it as the first message in that Claude Code session. The prompt contains:

- The session ID and worktree path
- The pre-selected specialist agent to use via the Agent tool
- The success criteria (from `tasks/phase-2b-heldout-synthesis.md` or equivalent)
- The heartbeat rule
- The exit rule (commit + PR + log transition to `READY-TO-MERGE`)

---

## While sessions are cooking

### Monitoring from the host

```bash
# Fleet status at a glance (status field of every session log)
grep -H "^status:" logs/sessions/*.md

# Sessions silent for > 30 minutes (stalled?)
./scripts/session_heartbeat.sh --audit

# Live tail of a specific session's log
tail -f logs/sessions/s1-heldout-synthesis.md

# All four sessions in a 2x2 tmux (if you use tmux)
tmux new-session -d -s act \; \
  split-window -h "tail -f logs/sessions/s1-heldout-synthesis.md" \; \
  split-window -v "tail -f logs/sessions/s2-card-violation-metric.md" \; \
  select-pane -t 0 \; split-window -v "tail -f logs/sessions/s3-bird-pilot-ingest.md" \; \
  select-pane -t 2 \; split-window -v "tail -f logs/sessions/s4-self-healing-loop.md" \; \
  attach
```

### Docker resource control

Each session runs its heavy compute inside a named container. If two sessions both try to run a 100M stress matrix, cap concurrency:

```bash
# Which containers are running now
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Size}}"

# Memory / CPU check
docker stats --no-stream

# If host is thrashing, pause the lowest-priority container
docker pause act-s4                     # self-healing track can wait
# ... when ready to resume
docker unpause act-s4
```

The accelerated plan's budget assumes **at most two** sessions running a 100M stress matrix at the same time. If three or four are lined up, queue through [merge-queue.md](../logs/merge-queue.md).

### Context recovery (session died)

If a Claude Code session crashes or hits context compression and loses where it was:

```bash
# From inside the worktree, resume:
cd worktrees/s1-heldout-synthesis
claude
```

Paste this recovery prompt:

```
Read logs/sessions/s1-heldout-synthesis.md top-to-bottom. Confirm current git branch,
then run `git log --oneline -5` and `git status` on this worktree. Report the frontmatter
`status:` value + what the last prose-timeline entry says the next action is. Resume from
there without redoing completed work.
```

The session reads its own log + git state and picks up deterministically.

---

## Finishing a session (from inside the Claude Code session)

When the session has met its success criteria:

```bash
# Inside the worktree, from Claude Code's Bash
git status                              # should be clean
git log --oneline origin/main..HEAD    # PR contents preview
git push -u origin session/s1-heldout-synthesis
gh pr create --title "$(head -1 logs/sessions/s1-heldout-synthesis.md)" --body-file logs/sessions/s1-heldout-synthesis.md
```

Then update the log frontmatter `status: READY-TO-MERGE` and append to [merge-queue.md](../logs/merge-queue.md):

```markdown
- [ ] s1-heldout-synthesis · PR #<n> · touches: benchmark/heldout_generator/, docs/heldout_generator_prompt.md, benchmark/questions_heldout.yaml, docs/heldout_predictions.md · merge ordering: before s2 (s2's scoreboard column reads the held-out logs)
```

The session is now done. Host closes the Claude Code session.

---

## The merge session (fifth session, after ≥2 of 4 land READY-TO-MERGE)

This is a **separate** Claude Code session on the main checkout (no worktree).

```bash
cd /Users/luanmorenomaciel/GitHub/agent-context-protocol
claude
```

Paste:

```
You are the merge-session for the parallel-sessions fleet. Read logs/merge-queue.md and
logs/sessions/*.md. For each PR marked READY-TO-MERGE:

1. Verify the PR's touched files do not conflict with already-merged PRs from this round.
2. Run `git checkout main && git pull && git merge --no-ff session/s<N>-<slug>`.
3. Run the session's success-criteria check (listed in that session's log frontmatter as `exit_check:`).
4. If check passes: push main, tick the merge-queue checkbox, archive the session log to logs/archive/.
5. If check fails: leave merged on main, open a follow-up task in tasks/backlog.md, still archive.

Never force-push. Never rewrite main's history. If two PRs have path conflicts, merge the one
listed first in the merge-queue; resolve conflicts in the second on its own branch and request
re-review.

Work through the queue in listed order. Do not reorder without human approval.
```

---

## Cleanup (after all four sessions are MERGED)

```bash
# Remove worktrees (keeps the branches for history; delete them only after merge commits exist on main)
git worktree list
git worktree remove worktrees/s1-heldout-synthesis
git worktree remove worktrees/s2-card-violation-metric
git worktree remove worktrees/s3-bird-pilot-ingest
git worktree remove worktrees/s4-self-healing-loop

# Optional: delete the session branches once you've confirmed they're in main
for s in s1-heldout-synthesis s2-card-violation-metric s3-bird-pilot-ingest s4-self-healing-loop; do
  git branch -d session/$s
  git push origin --delete session/$s
done

# Archive session logs (keep them under logs/archive/ for the honesty trail)
mkdir -p logs/archive/2026-04-24
mv logs/sessions/s[1-4]-*.md logs/archive/2026-04-24/

# Clear merge queue
: > logs/merge-queue.md
```

---

## Troubleshooting

| Symptom | Diagnosis | Fix |
|---|---|---|
| `session_init.sh` says worktree exists | Previous session wasn't cleaned up | `git worktree remove <path> --force` after checking no uncommitted work |
| Two sessions editing the same file | Crossed wires in task assignment | Stop one, revert its changes, let the other finish, then resume on `main` after merge |
| Session log silent > 30 min, no `BLOCKED` status | Claude Code crashed or hit context compression | Run the "Context recovery" flow from this doc |
| Docker container running but no log progress | Long stress run in flight — check `docker stats` | Wait; 100M × 3 LLMs × 3 seeds takes ~90 min wall |
| Merge conflict on `tasks/STATUS.md` | Multiple sessions tried to tick the same row | Expected. The merge session reconciles by taking union of green ticks |
| `docs/research.md` conflict | A session violated the non-negotiable rule | Revert that session's `docs/research.md` touch; paper edits happen in a dedicated writing session only |

---

## Why this is worth the setup cost

Serial execution of the accelerated plan: 10 calendar days.

Parallel with this orchestration:

| Component | Time saved | Failure it prevents |
|---|---:|---|
| 4 worktrees + 4 Claude sessions | ~6 days (D1–D5 parallelized) | — |
| Docker isolation | 0 days | OOM crashes from concurrent 100M runs |
| Session logs | ~1 day (no rediscovery after context loss) | Lost progress after compaction |
| Pre-picked agents | ~0.5 day (no tool-choice fumbling per session) | Wrong agent picks up a specialist task |
| Merge queue | ~0.5 day | Conflicts discovered during paper drafting |

Net: ~**8 days saved**, at the cost of ~2 hours of scaffolding setup (this file + PROMPTS.md + scripts). The ratio is why we do this.
