# Merge Queue

> Ordered list of session PRs ready to merge into `main`. Populated by sessions as they transition to `READY-TO-MERGE`. Consumed by the merge session (see [ORCHESTRATION.md](ORCHESTRATION.md) § The merge session).

**Ordering rules:**

1. Dependency order wins — if session B reads session A's artifacts (held-out logs, card-validator fix, etc.), A merges first.
2. Lower-risk PRs (infrastructure, tests) merge before higher-risk PRs (ARL changes, scoreboard rewrites).
3. Never reorder without a human note explaining why.

---

## Open (ready for the merge session)

<!-- Template row:
- [ ] s1-heldout-synthesis · PR #<n> · touches: <paths> · depends-on: <none | sX> · exit_check: <one-line>
-->

- [ ] s4-self-healing-loop · PR #10 · touches: benchmark/self_healing/*, benchmark/tests/fixtures/self_healing/, benchmark/tests/test_self_healing/*, scripts/run_shadow_benchmark.sh, docs/self_healing_arl_case_study.md, docs/self_healing_novelty.md · depends-on: none (scaffold uses synthetic fixtures, not s1/s2 outputs) · exit_check: merge_gate unit suite passes on main after merge
- [ ] s3-bird-pilot-ingest · PR #11 · touches: data/bird/*, benchmark/bird/*, benchmark/arl_bird_*, .gitignore · depends-on: none · exit_check: smoke tests per DB pass on main after merge

---

## Merged (this round)

_(empty — will fill as the merge session ticks rows)_

---

## Blocked / conflicted

_(empty — use when a PR can't merge cleanly; note why + next action)_
