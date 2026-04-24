#!/usr/bin/env bash
# session_finish.sh — run the exit checklist for a session
# Usage (from inside the worktree): ../../scripts/session_finish.sh <session-name>
#        or (from main repo root):  ./scripts/session_finish.sh <session-name>

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <session-name>" >&2
  exit 2
fi

NAME="$1"
BRANCH="session/${NAME}"

# Resolve main repo root (so relative paths work whether we're in a worktree or not)
REPO_ROOT="$(git rev-parse --show-toplevel)"
if [[ ! -d "${REPO_ROOT}/logs/sessions" ]]; then
  MAIN_ROOT="$(git worktree list --porcelain | awk '/^worktree/ {print $2; exit}')"
  if [[ -n "${MAIN_ROOT:-}" && -d "${MAIN_ROOT}/logs/sessions" ]]; then
    LOG="${MAIN_ROOT}/logs/sessions/${NAME}.md"
    QUEUE="${MAIN_ROOT}/logs/merge-queue.md"
  else
    echo "ERROR: could not locate logs/ directory from $(pwd)" >&2
    exit 1
  fi
else
  LOG="${REPO_ROOT}/logs/sessions/${NAME}.md"
  QUEUE="${REPO_ROOT}/logs/merge-queue.md"
fi

if [[ ! -f "${LOG}" ]]; then
  echo "ERROR: log ${LOG} not found." >&2
  exit 1
fi

echo "┌─ Exit checklist for ${NAME} ─────────────────────────────────────"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${CURRENT_BRANCH}" != "${BRANCH}" ]]; then
  echo "│  ✗ current branch is '${CURRENT_BRANCH}', expected '${BRANCH}'"
  echo "│    (you may be on main or a different worktree)"
  exit 1
fi
echo "│  ✓ on branch ${BRANCH}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "│  ✗ working tree is dirty — commit or stash before finishing"
  git status --short | sed 's/^/│    /'
  exit 1
fi
echo "│  ✓ working tree clean"

AHEAD="$(git rev-list --count origin/main..HEAD 2>/dev/null || git rev-list --count HEAD ^main)"
if [[ "${AHEAD}" -lt 1 ]]; then
  echo "│  ✗ no commits ahead of main — nothing to ship"
  exit 1
fi
echo "│  ✓ ${AHEAD} commit(s) ahead of main"

echo "│"
echo "│  Commits to ship:"
git log --oneline origin/main..HEAD 2>/dev/null || git log --oneline main..HEAD | sed 's/^/│    /'
echo "│"
echo "│  Next steps (manual — run from this worktree):"
echo "│    git push -u origin ${BRANCH}"
echo "│    gh pr create --title \"session/${NAME}\" --body-file ${LOG}"
echo "│"
echo "│  Then update ${LOG} frontmatter:"
echo "│    status: READY-TO-MERGE"
echo "│  And append a row to ${QUEUE}."
echo "└────────────────────────────────────────────────────────────────────"
