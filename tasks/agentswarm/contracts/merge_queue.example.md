# Merge Queue

> Ordered list of session PRs ready to merge into `main`. Populated by sessions
> as they transition to `READY-TO-MERGE`. Consumed by `anthive merge`.

**Ordering rules:**

1. Dependency order wins — if session B depends on session A, A merges first.
2. Lower-risk PRs (infrastructure, tests) before higher-risk PRs.
3. Never reorder without a human note explaining why.

---

## Open (ready for the merge session)

- [ ] s5-card-violator-fix · PR #23 · touches: benchmark/card_validator.py, benchmark/tests/test_card_validator.py · depends-on: none · exit_check: 9/9 tests pass on main after merge · spent: $0.08 · langfuse: abc-123
- [ ] s6-heldout-synth · PR #24 · touches: benchmark/heldout_generator/, benchmark/questions_heldout.yaml · depends-on: s5-card-violator-fix · exit_check: heldout suite green · spent: $1.42 · langfuse: def-456

---

## Merged (this round)

- [x] s4-self-healing-loop · PR #10 · touches: benchmark/self_healing/ · depends-on: none · exit_check: merge_gate suite passes · spent: $8.27 · langfuse: ghi-789

---

## Blocked / conflicted

_(empty — use when a PR can't merge cleanly; note why + next action)_
