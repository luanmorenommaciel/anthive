#!/usr/bin/env bash
# session_init.sh — scaffold a parallel Claude Code session
# Usage: ./scripts/session_init.sh <session-id> <slug>
# Example: ./scripts/session_init.sh s1 heldout-synthesis

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <session-id> <slug>" >&2
  echo "Example: $0 s1 heldout-synthesis" >&2
  exit 2
fi

SID="$1"
SLUG="$2"
NAME="${SID}-${SLUG}"
BRANCH="session/${NAME}"
WORKTREE="worktrees/${NAME}"
LOG="logs/sessions/${NAME}.md"
CONTAINER="act-${SID}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [[ ! -f "logs/sessions/_template.md" ]]; then
  echo "ERROR: logs/sessions/_template.md not found. Run from repo root with logs/ initialized." >&2
  exit 1
fi

if git worktree list --porcelain | grep -q "^worktree .*${WORKTREE}$"; then
  echo "ERROR: worktree ${WORKTREE} already exists." >&2
  echo "  To remove: git worktree remove ${WORKTREE}" >&2
  exit 1
fi

if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  echo "WARNING: branch ${BRANCH} already exists; attaching to it." >&2
  git worktree add "${WORKTREE}" "${BRANCH}"
else
  git worktree add -b "${BRANCH}" "${WORKTREE}"
fi

mkdir -p "logs/sessions"
if [[ -f "${LOG}" ]]; then
  echo "WARNING: ${LOG} already exists; not overwriting." >&2
else
  TODAY="$(date +%Y-%m-%d)"
  NOW="$(date +%Y-%m-%dT%H:%M:%S%z)"
  HEAD_SHA="$(git rev-parse --short=12 HEAD)"
  sed \
    -e "s|{{SID}}|${SID}|g" \
    -e "s|{{SLUG}}|${SLUG}|g" \
    -e "s|{{NAME}}|${NAME}|g" \
    -e "s|{{BRANCH}}|${BRANCH}|g" \
    -e "s|{{WORKTREE}}|${WORKTREE}|g" \
    -e "s|{{CONTAINER}}|${CONTAINER}|g" \
    -e "s|{{DATE}}|${TODAY}|g" \
    -e "s|{{NOW}}|${NOW}|g" \
    -e "s|{{HEAD_SHA}}|${HEAD_SHA}|g" \
    "logs/sessions/_template.md" > "${LOG}"
fi

cat <<EOF

╔════════════════════════════════════════════════════════════════════════╗
║  Session ${NAME} scaffolded.
╚════════════════════════════════════════════════════════════════════════╝

  Worktree   : ${WORKTREE}
  Branch     : ${BRANCH}
  Log        : ${LOG}
  Container  : ${CONTAINER}      (use this name for docker run --name)

Next steps:
  1. Open a terminal in the worktree:
       cd ${WORKTREE}

  2. Launch Claude Code:
       claude

  3. Paste the prompt for ${SID} from logs/PROMPTS.md.

  4. The session will update ${LOG} as it works.

To audit sessions (from repo root):
  grep -H "^status:" logs/sessions/*.md
  ./scripts/session_heartbeat.sh --audit

EOF
