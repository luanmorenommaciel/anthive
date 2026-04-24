"""anthive composer — deterministic session prompt generator.

Turns a TaskFrontmatter + agent definition + repo context into a frozen
prompt file that `anthive dispatch` consumes.  No LLM is called here;
the same (task, agents, repo) triple always produces identical bytes.

Public API:
    find_agent(agent_name, repo_root)  -> Path | None
    read_task_body(task_path)          -> str
    slugify(task_id)                   -> str
    session_id_for(task_id)            -> str
    compose(task, task_path, repo_root, other_active) -> str
"""

from __future__ import annotations

import re
from pathlib import Path

from .schemas import TaskFrontmatter

# ---------------------------------------------------------------------------
# Agent resolution
# ---------------------------------------------------------------------------


def find_agent(agent_name: str, repo_root: Path) -> Path | None:
    """Find the first .claude/agents/**/<agent_name>.md under repo_root.

    Search is deterministic: candidates are sorted alphabetically before
    the first match is returned.  This guarantees identical output even
    when the filesystem walk order differs across OS / Python versions.

    Args:
        agent_name: Bare name of the agent (e.g. ``"python-developer"``).
        repo_root:  Absolute path to the repository root.

    Returns:
        Absolute path to the agent definition file, or None if not found.
    """
    agents_root = repo_root / ".claude" / "agents"
    if not agents_root.exists():
        return None

    candidates = sorted(agents_root.rglob(f"{agent_name}.md"))
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Task body extraction
# ---------------------------------------------------------------------------


def read_task_body(task_path: Path) -> str:
    """Return the markdown body of a task file (everything after the closing ``---``).

    If no frontmatter block is present the entire file content is returned.

    Args:
        task_path: Absolute path to the task markdown file.

    Returns:
        The body text, stripped of leading/trailing blank lines.
    """
    text = task_path.read_text(encoding="utf-8")

    if not text.startswith("---"):
        return text.strip()

    # Skip the opening ---
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]

    close = rest.find("\n---")
    if close == -1:
        # Malformed frontmatter — return everything as body
        return text.strip()

    body = rest[close + 4:]   # skip '\n---'
    if body.startswith("\n"):
        body = body[1:]

    return body.strip()


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

# Matches T-YYYYMMDD- prefix (task-id prefix to strip for slug)
_TASK_DATE_PREFIX_RE = re.compile(r"^[Tt]-\d{8}-")


def slugify(task_id: str) -> str:
    """Derive a short, filesystem-safe worktree slug from a task id.

    Rules (applied in order):
    1. Lowercase the whole string.
    2. Strip a leading ``T-YYYYMMDD-`` prefix (8-digit date).
    3. Replace any character that is not ``[a-z0-9-]`` with ``-``.
    4. Collapse consecutive ``-`` into a single ``-``.
    5. Strip leading and trailing ``-``.

    Examples::

        T-20260424-card-violator-fix  →  card-violator-fix
        p3-dispatch-local             →  p3-dispatch-local
        B-FOO                         →  b-foo

    Args:
        task_id: A task ID string (validated by ``TaskFrontmatter``).

    Returns:
        A lowercase, hyphen-separated slug suitable for branch/dir names.
    """
    slug = task_id.lower()
    slug = _TASK_DATE_PREFIX_RE.sub("", slug)
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug


def session_id_for(task_id: str) -> str:
    """Return a stable session id derived from *task_id*.

    Format: ``sess-<slug>``  (e.g. ``sess-p2-compose``).

    Args:
        task_id: A task ID string.

    Returns:
        A session id string prefixed with ``sess-``.
    """
    return f"sess-{slugify(task_id)}"


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
You are running session `{session_id}` from a git worktree at
`{worktree}` on branch `{branch}`. Task ID: `{task_id}`.

═══════════════ GOAL ═══════════════
{task_body}

═══════════════ CONTEXT YOU MUST READ FIRST ═══════════════
{context_files_block}

═══════════════ PRIMARY AGENT ═══════════════
Use the `{agent_name}` specialist agent via the Agent tool
(subagent_type={agent_name}).
Agent definition: `{agent_path_rel}`

═══════════════ ALLOWED SURFACE ═══════════════
{allowed_paths_block}

═══════════════ DO-NOT-TOUCH LIST (hard) ═══════════════
{do_not_touch_block}

═══════════════ HEARTBEAT RULE ═══════════════
- Every meaningful state change, run:
    anthive heartbeat {session_id} COOKING "<one-line note>"
- Status transitions: INIT → COOKING → CHECKPOINT → READY-TO-MERGE
- Silent > 30 min with status COOKING = stalled. Heartbeat at least every 10 min.

═══════════════ EXIT RULE ═══════════════
{exit_check}

When done:
  anthive heartbeat {session_id} READY-TO-MERGE "<one-line note>"
  git push -u origin {branch}
  gh pr create --fill
Then append the row to logs/merge-queue.md.

═══════════════ FIRST ACTIONS (in order) ═══════════════
1. Read `logs/sessions/{session_id}.md` and fill its Goal / Success criteria
   / touches_paths fields from this prompt.
2. Heartbeat: `anthive heartbeat {session_id} COOKING "starting"`
3. Begin implementation per the GOAL block above.

═══════════════ AUTONOMY DIRECTIVE ═══════════════
**Do not stop to ask whether to fill in the session log fields — fill them
yourself from the GOAL above, commit that fill-in as your first commit with
message `chore({task_id}): fill session log from task doc`, and proceed.
Only pause for a human when you hit a genuine blocker.**

Start now.
"""


# ---------------------------------------------------------------------------
# Context-file helpers
# ---------------------------------------------------------------------------


def _build_context_files_block(
    task: TaskFrontmatter,
    task_path: Path,
    repo_root: Path,
) -> str:
    """Build the numbered context-files list for the prompt.

    Includes (in sorted order, deduplicated):
    - The task spec file itself
    - CLAUDE.md at repo root (if it exists)
    - tasks/PLAN.md (if it exists)
    - Each path in task.touches_paths that already exists on disk
    """
    entries: set[str] = set()

    # Always include the task spec path (relative to repo_root)
    try:
        rel_task = str(task_path.relative_to(repo_root))
    except ValueError:
        rel_task = str(task_path)
    entries.add(rel_task)

    # Always include CLAUDE.md if it exists
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        entries.add("CLAUDE.md")

    # Always include tasks/PLAN.md if it exists
    plan_md = repo_root / "tasks" / "PLAN.md"
    if plan_md.exists():
        entries.add("tasks/PLAN.md")

    # Add each touches_paths entry that already exists
    for p in task.touches_paths:
        candidate = repo_root / p
        if candidate.exists():
            entries.add(p)

    sorted_entries = sorted(entries)
    lines = [f"{i + 1}. `{path}` — context" for i, path in enumerate(sorted_entries)]
    return "\n".join(lines)


def _build_allowed_paths_block(task: TaskFrontmatter) -> str:
    """Render the sorted allowed-surface bullet list."""
    paths = sorted(task.touches_paths)
    if not paths:
        return "(none declared — be conservative)"
    return "\n".join(f"- `{p}`" for p in paths)


def _build_do_not_touch_block(do_not_touch: list[str]) -> str:
    """Render the sorted do-not-touch bullet list."""
    if not do_not_touch:
        return "(none — no other active tasks declared touches_paths)"
    return "\n".join(f"- `{p}`" for p in do_not_touch)


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def compose(
    task: TaskFrontmatter,
    task_path: Path,
    repo_root: Path,
    other_active: list[TaskFrontmatter],
) -> str:
    """Render the full session prompt as a string.

    This function is deterministic: identical inputs always produce identical
    output bytes.  All list operations sort their elements before rendering.

    Args:
        task:         The task whose prompt we are generating.
        task_path:    Absolute path to the task markdown file on disk.
        repo_root:    Absolute path to the repository root.
        other_active: Tasks that are currently ready or in-progress (used to
                      compute the do-not-touch list).  Must NOT include ``task``
                      itself — callers are responsible for filtering.

    Returns:
        The full prompt text (UTF-8 string, no trailing newline beyond the
        template's own ``"Start now."`` line).

    Raises:
        ValueError: If the agent definition file cannot be found under
                    ``.claude/agents/``.
    """
    # 1. Resolve agent
    agent_path = find_agent(task.agent, repo_root)
    if agent_path is None:
        raise ValueError(
            f"Agent {task.agent!r} not found under "
            f"{(repo_root / '.claude' / 'agents')!s}"
        )

    agent_path_rel = str(agent_path.relative_to(repo_root))

    # 2. Read task body
    task_body = read_task_body(task_path)

    # 3. Compute do-not-touch paths:
    #    union of all other_active touches_paths, minus task's own touches_paths
    own_paths: set[str] = set(task.touches_paths)
    other_paths: set[str] = set()
    for other in other_active:
        other_paths.update(other.touches_paths)
    do_not_touch = sorted(other_paths - own_paths)

    # 4. Compute context files
    context_files_block = _build_context_files_block(task, task_path, repo_root)

    # 5. Derive session / worktree / branch names
    slug = slugify(task.id)
    session_id = session_id_for(task.id)
    worktree = f"worktrees/{slug}"
    branch = f"session/{slug}"

    # 6. Render blocks
    allowed_paths_block = _build_allowed_paths_block(task)
    do_not_touch_block = _build_do_not_touch_block(do_not_touch)

    # 7. Exit check — TaskFrontmatter has no exit_check field; use generic fallback
    exit_check = "All success criteria from the GOAL block satisfied; tests green."

    return PROMPT_TEMPLATE.format(
        session_id=session_id,
        worktree=worktree,
        branch=branch,
        task_id=task.id,
        task_body=task_body,
        context_files_block=context_files_block,
        agent_name=task.agent,
        agent_path_rel=agent_path_rel,
        allowed_paths_block=allowed_paths_block,
        do_not_touch_block=do_not_touch_block,
        exit_check=exit_check,
    )
