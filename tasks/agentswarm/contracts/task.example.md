---
id: T-20260424-card-violator-fix
title: "Fix card_validator alias bug"
status: ready
effort: S
budget_usd: 0
agent: llm-evaluator-designer
depends_on: []
touches_paths:
  - benchmark/card_validator.py
  - benchmark/tests/test_card_validator.py
source: notes/2026-04-24-standup.md#L47
created: 2026-04-24T16:30:00-03:00
prefer_model: sonnet
mode: local
max_turns: 50
tags: ["validator", "tech-debt"]
---

# Fix card_validator alias bug

The `card_validator` module silently accepts aliased column names without
flagging them as schema violations. Tests covering the alias path expose the
bug — they currently fail.

## Success criteria

- `card_validator.validate(payload)` returns a `CardViolation` when a payload
  references an aliased column not declared in the schema card
- 9/9 tests in `benchmark/tests/test_card_validator.py` pass
- No regression in the existing 47 tests

## Tasks

1. Reproduce the bug with a failing test
2. Trace alias resolution in `_resolve_columns`
3. Fix the resolution path so aliases are checked against declared columns
4. Ensure the fix preserves backwards-compat for legitimate aliases

## Do-not-touch list

- `benchmark/harness.py` (other sessions touch this)
- `docs/research.md` (paper draft — reserved for the writing session)
