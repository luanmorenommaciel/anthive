#!/usr/bin/env bash
# session_heartbeat.sh — update / audit session heartbeat
# Usage:
#   Inside a session (from repo root OR worktree):
#       ./scripts/session_heartbeat.sh <session-name> <status> ["optional note"]
#     ex: ./scripts/session_heartbeat.sh s1-heldout-synthesis COOKING "generating 120 candidates"
#
#   Audit mode (from host):
#       ./scripts/session_heartbeat.sh --audit
#     lists sessions and flags any with heartbeat older than 30 minutes.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# If we're inside a worktree, walk up to find the main repo's logs/
if [[ ! -d "${REPO_ROOT}/logs/sessions" ]]; then
  MAIN_ROOT="$(git worktree list --porcelain 2>/dev/null | awk '/^worktree/ {print $2; exit}')"
  if [[ -n "${MAIN_ROOT:-}" && -d "${MAIN_ROOT}/logs/sessions" ]]; then
    REPO_ROOT="${MAIN_ROOT}"
  fi
fi

if [[ "${1:-}" == "--audit" ]]; then
  NOW_EPOCH="$(date +%s)"
  STALE_THRESHOLD=1800   # 30 minutes

  printf "%-30s  %-18s  %-8s  %s\n" "SESSION" "STATUS" "AGE" "LAST NOTE"
  printf "%-30s  %-18s  %-8s  %s\n" "-------" "------" "---" "---------"

  shopt -s nullglob
  for f in "${REPO_ROOT}/logs/sessions/"*.md; do
    base="$(basename "$f" .md)"
    [[ "$base" == "_template" ]] && continue

    status=$(grep -m1 "^status:" "$f" 2>/dev/null | awk '{print $2}')
    heartbeat=$(grep -m1 "^last_heartbeat:" "$f" 2>/dev/null | awk '{print $2}')
    note=$(grep -m1 "^last_note:" "$f" 2>/dev/null | sed 's/^last_note:[[:space:]]*//' | head -c 60)

    if [[ -n "${heartbeat:-}" && "${heartbeat}" != "null" ]]; then
      # Parse ISO-8601 via date or Python fallback
      hb_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "${heartbeat}" +%s 2>/dev/null || \
                 python3 -c "import sys,datetime;print(int(datetime.datetime.fromisoformat(sys.argv[1]).timestamp()))" "${heartbeat}" 2>/dev/null || echo "0")
      age=$((NOW_EPOCH - hb_epoch))
      if (( age > STALE_THRESHOLD )) && [[ "${status:-}" != "MERGED" && "${status:-}" != "READY-TO-MERGE" && "${status:-}" != "BLOCKED" ]]; then
        age_tag=$(printf "%dm ⚠" $((age/60)))
      else
        age_tag=$(printf "%dm" $((age/60)))
      fi
    else
      age_tag="--"
    fi

    printf "%-30s  %-18s  %-8s  %s\n" "${base}" "${status:-UNKNOWN}" "${age_tag}" "${note:-}"
  done
  exit 0
fi

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <session-name> <status> [\"note\"]" >&2
  echo "       $0 --audit" >&2
  exit 2
fi

NAME="$1"
NEW_STATUS="$2"
NOTE="${3:-}"
LOG="${REPO_ROOT}/logs/sessions/${NAME}.md"

if [[ ! -f "${LOG}" ]]; then
  echo "ERROR: log ${LOG} not found. Run scripts/session_init.sh first." >&2
  exit 1
fi

case "${NEW_STATUS}" in
  INIT|COOKING|CHECKPOINT|READY-TO-MERGE|MERGED|BLOCKED) ;;
  *)
    echo "ERROR: status must be one of INIT, COOKING, CHECKPOINT, READY-TO-MERGE, MERGED, BLOCKED" >&2
    exit 2
    ;;
esac

NOW="$(date +%Y-%m-%dT%H:%M:%S%z)"

# Update frontmatter fields in place (portable across macOS/Linux via tmpfile)
TMP="$(mktemp)"
awk -v now="${NOW}" -v status="${NEW_STATUS}" -v note="${NOTE}" '
  BEGIN { fm = 0 }
  /^---$/ { fm++ }
  fm == 1 && /^status:/ { print "status: " status; next }
  fm == 1 && /^last_heartbeat:/ { print "last_heartbeat: " now; next }
  fm == 1 && /^last_note:/ { if (note != "") print "last_note: " note; else print; next }
  { print }
' "${LOG}" > "${TMP}" && mv "${TMP}" "${LOG}"

# Append a prose-timeline line so the history is visible
{
  echo ""
  echo "- **${NOW}** · \`${NEW_STATUS}\`${NOTE:+ · ${NOTE}}"
} >> "${LOG}"

echo "heartbeat updated: ${NAME} → ${NEW_STATUS}${NOTE:+ (${NOTE})}"
