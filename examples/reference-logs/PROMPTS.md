# Copy-Paste Prompts for Parallel Sessions

> Four prompts, one per track. Each is self-contained: the session reads the prompt, picks the right specialist agent via the Agent tool, follows the plan, heartbeats to its log file, exits via a PR. See [ORCHESTRATION.md](ORCHESTRATION.md) for the host-side setup that must happen **before** you paste any of these.

---

## Before you paste any prompt

From the main checkout, run **one** of these to scaffold the session:

```bash
./scripts/session_init.sh s1 heldout-synthesis
./scripts/session_init.sh s2 card-violation-metric
./scripts/session_init.sh s3 bird-pilot-ingest
./scripts/session_init.sh s4 self-healing-loop
```

Then `cd worktrees/<name>` and launch `claude` in that directory. Paste the matching prompt below as the **first** message.

---

## s1 — Held-out LLM Synthesis (Phase 2B)

**Worktree:** `worktrees/s1-heldout-synthesis/` · **Branch:** `session/s1-heldout-synthesis` · **Container:** `act-s1`

> Copy everything between the fences and paste as the first message in the Claude Code session started inside `worktrees/s1-heldout-synthesis/`.

````
You are running session `s1-heldout-synthesis` from a git worktree at
`worktrees/s1-heldout-synthesis/` on branch `session/s1-heldout-synthesis`. The
main repo is at the sibling path (one level up from the worktree root's parent).

═══════════════ GOAL (single sentence) ═══════════════
Execute Phase 2B — build the LLM-generated held-out question pipeline and run it
to 100 frozen questions, following `tasks/phase-2b-heldout-synthesis.md` verbatim
under Guardrails A and B, and ship the result as a PR on this session's branch.

═══════════════ CONTEXT YOU MUST READ FIRST ═══════════════
1. `tasks/phase-2b-heldout-synthesis.md` — the full plan (your spec)
2. `tasks/accelerated-plan.md` § "D1–D3" — how this session fits the schedule
3. `logs/README.md` + `logs/ORCHESTRATION.md` — the coordination rules
4. `benchmark/schema_card.py` — where the ACT-P DDL comes from
5. `benchmark/llm_client.py` — the OpenRouter client this session will use
6. `benchmark/questions.yaml` — DO NOT OPEN (it is held-in; Guardrail A.2 forbids)

═══════════════ PRIMARY AGENT ═══════════════
Use the `schema-card-author` specialist agent from `.claude/agents/research/`
for anything touching the ACT-P surface → card-schema contract. Use the
`llm-specialist` agent from `.claude/agents/python/` for any prompt-engineering
work on the generator prompt itself. Use `benchmark-harness-engineer` from
`.claude/agents/research/` when wiring the eval run.

When you invoke an agent, use the Agent tool with subagent_type = the agent's
`name:` from its frontmatter (e.g. `schema-card-author`).

═══════════════ DO-NOT-TOUCH LIST (hard) ═══════════════
- `docs/research.md`  (paper draft — reserved for the writing session)
- `benchmark/questions.yaml`  (held-in — Guardrail A.2)
- `benchmark/reading_layer.py`, `benchmark/arl_versions.py`  (ARL — Guardrail A.2)
- `results/research/`  (ablation / scoreboard results — Guardrail A.2)
- Anything outside `benchmark/heldout_generator/`, `docs/heldout_generator_prompt.md`,
  `docs/heldout_predictions.md`, `benchmark/questions_heldout.yaml`,
  `results/stress/*_heldout.log`, `results/ground_truth_heldout_FROZEN_*.json`

═══════════════ GUARDRAIL ENFORCEMENT (non-negotiable) ═══════════════
Before writing `benchmark/heldout_generator/driver.py`, add an assert that
explicitly excludes the eval set from the generator set:

    EVAL_EXCLUSION = {"opus-4.7", "gpt-5.4", "gemini-2.5",
                      "claude-opus-4-7", "openai/gpt-5.4",
                      "google/gemini-2.5-flash"}
    assert not (set(generator_models) & EVAL_EXCLUSION), \
        f"Guardrail A.1 violation: generator set overlaps eval set"

Freeze-before-run ordering (Guardrail B.2) — the `heldout-v1-frozen` tag MUST
precede the first harness invocation. Enforce by having the run step refuse to
start if `git tag -l heldout-v1-frozen` is empty on this branch.

═══════════════ HEARTBEAT RULE ═══════════════
- Every meaningful state change, run:
    ../../scripts/session_heartbeat.sh s1-heldout-synthesis COOKING "<one-line note>"
- When you finish a step from the plan, change status:
    CHECKPOINT  — step committed, moving to next
    READY-TO-MERGE  — all steps done, PR is open
    BLOCKED  — you need a human (ALSO: write the blocker in the log prose)
- Silent > 30 min with status COOKING = stalled. Don't let it happen — heartbeat
  at least once per long-running compute call.

═══════════════ EXIT RULE ═══════════════
Success criteria (from phase-2b-heldout-synthesis.md § "Success Criteria"):

  1. Guardrail A enforced (generator ∩ eval = ∅) — verified in code
  2. Guardrail B enforced (heldout-v1-frozen tag precedes any run) — verified in git log
  3. 100 questions in `benchmark/questions_heldout.yaml`
  4. Distribution balance: ~33/33/33 tier split, ≥10 per question class, ≥20 per table-scope
  5. `docs/heldout_predictions.md` committed BEFORE the eval run
  6. 3 LLMs × 3 seeds × 100 questions @ 100M ran and logs are in `results/stress/*_heldout.log`
  7. Actuals reported against predictions (§ "Actual Results" appended to heldout_predictions.md)
  8. §8.17.12 subsection written in a staged diff (NOT committed to docs/research.md — leave it as a patch file at `docs/heldout_synthesis_sec8_17_12.patch` for the writing session to apply)

When all eight are true:
  ../../scripts/session_finish.sh s1-heldout-synthesis
Then push the branch and open the PR, update the log status to READY-TO-MERGE,
and append the row to logs/merge-queue.md (template row is in that file).

═══════════════ FIRST ACTIONS (in order) ═══════════════
1. Read `logs/sessions/s1-heldout-synthesis.md` and fill the Purpose / Goal /
   Success criteria / Do-not-touch / touches_paths / primary_agent fields.
2. Heartbeat: `../../scripts/session_heartbeat.sh s1-heldout-synthesis COOKING "starting Step 0"`
3. Execute Step 0 (skeleton) of phase-2b-heldout-synthesis.md.
4. Commit with message `feat(heldout): Step 0 — generator package skeleton`.
5. Continue through Steps 1, 2, 3 per the plan, heartbeating between them.

Start now. First real tool call should be reading the log file and the plan.

**Do not stop to ask whether to fill in the Goal / Success criteria / touches_paths fields — fill them yourself from the referenced plan, commit that fill-in as your first commit with message `chore(<sid>): fill session log from <plan> plan`, and proceed. Only pause for a human when you hit a genuine blocker (missing credential, a merge-conflict you cannot resolve safely, or an explicit ambiguity the plan does not cover).**
````

---

## s2 — CARD_VIOLATION as First-Class Metric (Phase 4B Track 1)

**Worktree:** `worktrees/s2-card-violation-metric/` · **Branch:** `session/s2-card-violation-metric` · **Container:** `act-s2`

````
You are running session `s2-card-violation-metric` from a git worktree at
`worktrees/s2-card-violation-metric/` on branch `session/s2-card-violation-metric`.

═══════════════ GOAL (single sentence) ═══════════════
Execute Phase 4B Track 1 — fix the card_validator SELECT-alias bug, backfill
CARD_VIOLATION rate into `results/stress/summary.csv` and the scoreboard tables
in two docs, and ship the result as a PR. No new benchmark runs; this is a
metric-promotion + data-refresh session.

═══════════════ CONTEXT YOU MUST READ FIRST ═══════════════
1. `tasks/phase-4b-self-healing-arl.md` § "Track 1" — the full Track 1 plan
2. `tasks/accelerated-plan.md` § "D1" — how this fits
3. `tasks/backlog.md` § "B-CARD-VALIDATOR-ALIAS-FIX" — the bug you're fixing
4. `benchmark/card_validator.py` — the module you're fixing
5. `benchmark/aggregate_stress.py` — the aggregator you're extending
6. `docs/metrics.md` § 2 (verdict vocabulary) and § 4 (limits)
7. `docs/act-arl-summary.md` § "Canonical Scoreboard" + § "Headline Table"

═══════════════ PRIMARY AGENT ═══════════════
Use the `llm-evaluator-designer` specialist agent from `.claude/agents/research/`
for anything touching verdict semantics and the `extract_references()` alias fix.
Use `test-generator` from `.claude/agents/test/` for the pytest suite under
`benchmark/tests/test_card_validator.py`. Use `results-analyst` from
`.claude/agents/research/` for the scoreboard backfill.

═══════════════ DO-NOT-TOUCH LIST ═══════════════
- `benchmark/reading_layer.py`, `benchmark/arl_versions.py`, `benchmark/schema_card.py`
  (ARL + schema — out of scope for Track 1)
- `benchmark/questions.yaml`, `benchmark/questions_heldout.yaml`
- `benchmark/self_healing/`  (Track 2's surface — different session)
- `benchmark/heldout_generator/`  (s1's surface)
- `data/bird/`  (s3's surface)

Allowed surface:
- `benchmark/card_validator.py` (fix)
- `benchmark/tests/test_card_validator.py` (new file)
- `benchmark/aggregate_stress.py` (extend to emit card_violation_rate)
- `results/stress/summary.csv` (regenerated; committed)
- `docs/research.md` §8.17.11 (ADD a column; do NOT rewrite other sections)
  → actually, per the DO-NOT-TOUCH list in the template, stage as a patch at
    `docs/card_violation_sec8_17_11.patch` for the writing session.
- `docs/act-arl-summary.md` (add the Card-Violation % column to the Headline Table)
- `docs/metrics.md` § 4 (promote CARD_VIOLATION from "not reported" to headline)

═══════════════ HEARTBEAT RULE ═══════════════
Same as s1. Heartbeat script path from your worktree: `../../scripts/session_heartbeat.sh`.

═══════════════ EXIT RULE ═══════════════
Success criteria (from phase-4b-self-healing-arl.md § "Track 1 · Success Criteria"):

  1. `card_validator.py` handles SELECT-list aliases in ORDER BY / HAVING
  2. ≥4 unit tests covering: alias in ORDER BY, alias in HAVING, nested alias,
     non-alias real column, mixed alias+real
  3. `results/stress/summary.csv` has `card_violation_rate` column populated
     for all existing logs (3NF, v7 FINAL, v8 ARL_V3, V3_LEAN × 3 LLMs × 3 seeds @ 100M)
  4. `docs/act-arl-summary.md` Headline Table has a new `Card-Violation %` column
  5. `docs/metrics.md` § 4 updated; CARD_VIOLATION definition + worked example
     + honest-limit note present
  6. A staged patch at `docs/card_violation_sec8_17_11.patch` for the paper session
  7. All pytests green: `pytest benchmark/tests/test_card_validator.py -v`
  8. Hypothesis-vs-actual note in the log: did 3NF > v7 > v8 on violation rate?
     Report what the data says; do not massage.

Exit via `../../scripts/session_finish.sh s2-card-violation-metric`, then PR.

═══════════════ FIRST ACTIONS ═══════════════
1. Fill the log frontmatter + body.
2. Heartbeat COOKING "starting alias-bug fix".
3. Read `benchmark/card_validator.py::extract_references()` end-to-end before editing.
4. Write the test file first (TDD) covering the four alias scenarios, run it,
   confirm failures, then fix the validator, confirm green.

Start now.
````

---

## s3 — BIRD Pilot Ingest (Phase 3)

**Worktree:** `worktrees/s3-bird-pilot-ingest/` · **Branch:** `session/s3-bird-pilot-ingest` · **Container:** `act-s3`

````
You are running session `s3-bird-pilot-ingest` from a git worktree at
`worktrees/s3-bird-pilot-ingest/` on branch `session/s3-bird-pilot-ingest`.

═══════════════ GOAL (single sentence) ═══════════════
Execute Phase 3 Step 3.0 — ingest 3 BIRD pilot databases as DuckDB/Parquet, then
author one ARL per database following the ACT-P + ACT-R pattern, ship frozen
tags `bird-arl-<db>-v1-frozen`, and leave the pilot ready for the eval run that
s1's generator (once it lands) will populate with per-DB held-out questions.

═══════════════ CONTEXT YOU MUST READ FIRST ═══════════════
1. `tasks/phase-3.md` § "Step 3.0 — BIRD-lite Pilot" — the full plan
2. `tasks/accelerated-plan.md` § "D1–D4" — how this fits
3. `benchmark/schema_card.py` — the reference for how an ACT-P DDL is shaped
4. `benchmark/reading_layer.py::ARL_V1` — the reference for ARL card structure

═══════════════ PRIMARY AGENT ═══════════════
Use the `duckdb-specialist` agent from `.claude/agents/research/` for all SQLite→DuckDB
conversion + Parquet export work. Use `schema-card-author` from `.claude/agents/research/`
for the per-DB ARL authoring (it knows the six-card protocol).

═══════════════ PILOT DB SELECTION ═══════════════
From `tasks/phase-3.md` § T3.0.1 — select exactly these 3 for the D1–D4 window
(not all 5; D6 extends to 5):

  - `financial`                  (stresses [windows] + [freshness])
  - `california_schools`         (stresses [projections]; temporal-irrelevant)
  - `debit_card_specializing`    (stresses [metrics] + [constraints])

═══════════════ DO-NOT-TOUCH LIST ═══════════════
- `benchmark/schema_card.py`, `benchmark/reading_layer.py`, `benchmark/arl_versions.py`
  (the e-commerce ARL — read-only reference)
- `benchmark/heldout_generator/` (s1)
- `benchmark/card_validator.py`, `benchmark/self_healing/` (s2, s4)
- `docs/research.md`

Allowed:
- `data/bird/<db>/` — all three pilot DBs
- `benchmark/arl_bird_financial.py`, `benchmark/arl_bird_california_schools.py`,
  `benchmark/arl_bird_debit_card_specializing.py`
- `benchmark/schema_card_bird.py` — the ACT-P-equivalent DDL emitter per DB
- `scripts/ingest_bird_<db>.sh` — one per DB

═══════════════ HEARTBEAT RULE ═══════════════
Same as s1 / s2.

═══════════════ EXIT RULE ═══════════════
Success criteria (subset of phase-3.md § "BIRD-lite pilot" for the D1–D4 window):

  1. 3 DBs ingested; `data/bird/<db>/3nf/*.parquet` exists per DB
  2. `data/bird/<db>/HASHES.txt` committed per DB
  3. 3 ARLs authored; each ≤ 1000 tokens rendered
  4. Each ARL smoke-tested against a single trivial question (e.g. row count per
     main table) under `benchmark/harness.py` at 10% sample — verifies the ARL
     renders without `CARD_VIOLATION` on the sanity question
  5. `bird-arl-financial-v1-frozen`, `bird-arl-california_schools-v1-frozen`,
     `bird-arl-debit_card_specializing-v1-frozen` tags pushed on the session branch
  6. A README per DB at `data/bird/<db>/README.md` explaining: source URL,
     import command, row counts per table, ARL location, known BIRD-evaluator quirks
  7. (Reuse hook) Once s1's generator is PR'd, a follow-up session can feed each
     DB's ACT-P DDL into that driver to produce per-DB held-out questions. Note
     this in the session log so the follow-up knows where to start.

Exit via `../../scripts/session_finish.sh s3-bird-pilot-ingest`, then PR.

═══════════════ FIRST ACTIONS ═══════════════
1. Fill the log frontmatter + body.
2. Heartbeat COOKING "pulling BIRD Mini-Dev".
3. Fetch BIRD Mini-Dev (see `tasks/phase-3.md` § T3.0.2 for the canonical URL);
   commit SHA256 of the archive to `data/bird/BIRD_MINIDEV_SOURCE.md`.
4. Ingest `financial` first (smallest); author its ARL; smoke-test; tag.
5. Repeat for the other two.

Start now.
````

---

## s4 — Self-Healing Loop Scaffold (Phase 4B Track 2)

**Worktree:** `worktrees/s4-self-healing-loop/` · **Branch:** `session/s4-self-healing-loop` · **Container:** `act-s4`

````
You are running session `s4-self-healing-loop` from a git worktree at
`worktrees/s4-self-healing-loop/` on branch `session/s4-self-healing-loop`.

═══════════════ GOAL (single sentence) ═══════════════
Execute Phase 4B Track 2 scaffold — build the four modules (violation miner,
cluster engine, card-edit author, shadow-benchmark runner, merge gate) with
unit tests against synthetic fixtures so the loop is runnable the moment s1's
held-out logs land.

═══════════════ CONTEXT YOU MUST READ FIRST ═══════════════
1. `tasks/phase-4b-self-healing-arl.md` § "Track 2" — the full plan (your spec)
2. `tasks/accelerated-plan.md` § "D4–D5" — how this fits (blocks on s1 held-out logs)
3. `benchmark/card_validator.py` (after s2's fix) — this is where violations come from
4. `benchmark/reading_layer.py` — what the card-edit author proposes diffs against
5. `benchmark/harness.py` — how shadow runs are invoked

═══════════════ PRIMARY AGENT ═══════════════
Use the `llm-specialist` agent from `.claude/agents/python/` for the card-edit
author LLM-calling code (it must use a non-eval LLM — same Guardrail A.1 as s1).
Use the `benchmark-harness-engineer` agent from `.claude/agents/research/` for
the shadow-benchmark runner + merge gate. Use `code-reviewer` from
`.claude/agents/code-quality/` before PR'ing — the merge gate is load-bearing
and must be strict.

═══════════════ DO-NOT-TOUCH LIST ═══════════════
- `benchmark/card_validator.py` (s2 owns this)
- `benchmark/heldout_generator/` (s1)
- `benchmark/schema_card.py`, `benchmark/reading_layer.py`, `benchmark/arl_versions.py`
  — READ-ONLY. The self-healing loop proposes *diffs* against these files;
  it does not commit the diffs. Shadow runs apply the diff on a scratch branch
  that is deleted after measurement.
- `data/bird/` (s3)

Allowed:
- `benchmark/self_healing/__init__.py`
- `benchmark/self_healing/violation_miner.py`
- `benchmark/self_healing/cluster.py`
- `benchmark/self_healing/propose_edit.py`
- `benchmark/self_healing/merge_gate.py`
- `benchmark/self_healing/apply_edit.py`  (scratch-branch edit applier)
- `benchmark/tests/test_self_healing_*.py`
- `scripts/run_shadow_benchmark.sh`
- `results/self_healing/README.md` (describing what artifacts land here)

═══════════════ GUARDRAIL (Track 2 specific) ═══════════════
The card-edit-author LLM must satisfy `G ∩ E = ∅` — same rule as s1's
Guardrail A.1. Hard-code the exclusion set in `propose_edit.py`:

    CARD_EDIT_AUTHOR_EXCLUSION = {"opus-4.7", "gpt-5.4", "gemini-2.5", ...}
    assert proposal_model not in CARD_EDIT_AUTHOR_EXCLUSION

═══════════════ SYNTHETIC FIXTURES (for D4 scaffold) ═══════════════
s1's held-out logs will not exist until s1 PRs. For this scaffold session, build
synthetic fixtures under `benchmark/tests/fixtures/self_healing/`:

  - `violations_synthetic.json` — 20 hand-crafted violation records
  - `clusters_expected.json` — what the clusterer should produce from those 20
  - `proposal_expected.json` — a known-good card edit for one cluster

Tests assert the pipeline produces the expected outputs on the synthetic fixtures.
When real held-out logs land post-s1-merge, the same pipeline runs on real data.

═══════════════ HEARTBEAT RULE ═══════════════
Same as s1 / s2 / s3.

═══════════════ EXIT RULE ═══════════════
Success criteria (from phase-4b-self-healing-arl.md § "Track 2 · Success Criteria"):

  1. Five modules exist and pass unit tests on synthetic fixtures
  2. `scripts/run_shadow_benchmark.sh` executes end-to-end against a toy ARL diff
     on the 10M held-in sample (NOT on 100M — this is a scaffold smoke test)
  3. `merge_gate.py` strict-conjunction gate is implemented and has tests for
     the four rejection reasons (violations ↑, held-in CORRECT ↓, held-out
     CORRECT ↓, quorum ↓) — each test synthesizes a "failing shadow result"
     and asserts REJECT
  4. `docs/self_healing_arl_case_study.md` committed as a stub with the
     template for the real D5 case study (one end-to-end cycle, to be filled
     once held-out logs land)
  5. Novelty-check placeholder at `docs/self_healing_novelty.md` — one page
     with search queries to run on D5; NOT the full literature survey
  6. Each module has a top-of-file docstring naming its upstream input and
     downstream output so the pipeline is readable start-to-end

Exit via `../../scripts/session_finish.sh s4-self-healing-loop`, then PR.

═══════════════ FIRST ACTIONS ═══════════════
1. Fill the log frontmatter + body.
2. Heartbeat COOKING "scaffold starting — package skeleton".
3. Create `benchmark/self_healing/__init__.py` + the five module files as
   empty stubs with docstrings.
4. Write the synthetic fixture first (`violations_synthetic.json`), then the
   first test that consumes it, then the miner, then green.
5. Proceed: cluster → propose → apply → merge-gate → shadow script.

Start now.
````

---

## Notes for the human operator

### Suggested order for pasting

If your host has budget for all four concurrent, start them in this order:

1. **s2 first** (CARD_VIOLATION metric) — 1 day, cheapest, enables cleaner s1 data downstream
2. **s1 next** (held-out synthesis) — 2 days, is the longest critical path
3. **s3 in parallel with s1** (BIRD ingest) — 2–3 days, independent surface
4. **s4 starts when s2's card_validator fix lands on main** — the scaffold uses the fixed validator

### Suggested order if host is resource-constrained

Run s2 → s1 → (s3 and s4 in parallel) in pairs instead of all four. The total wall time doubles from ~3 days to ~6 days but the accelerated plan still beats the 10-day serial.

### If a session gets confused

Paste the recovery prompt from `logs/ORCHESTRATION.md` § "Context recovery". Every session's log is designed to be readable cold — a new session can pick up where the crashed one left off without any shared memory.

### The merge session

When any two sessions hit `READY-TO-MERGE`, open the merge session per `logs/ORCHESTRATION.md` § "The merge session". Do not let a PR sit in the queue for more than a day — stale PRs rot fastest in parallel work.
