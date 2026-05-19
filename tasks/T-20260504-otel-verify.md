---
id: T-20260504-otel-verify
title: "Verify Claude Code child sessions emit OTEL spans nested under anthive's parent span"
status: ready
effort: S
budget_usd: 0
agent: python-developer
depends_on: [T-20260504-langfuse-verify]
touches_paths:
  - docs/observability-runbook.md
  - anthive/dispatchers/local.py
created: 2026-05-04T00:00:00-0300
tags: ["observability", "verification", "otel", "claude-code"]
---

# T-20260504-otel-verify — Claude Code OTEL emission verification

> **Why:** the dispatcher injects `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and `OTEL_RESOURCE_ATTRIBUTES` into the child tmux process ([dispatchers/local.py:336-340](anthive/dispatchers/local.py#L336-L340)). The unit tests confirm those env vars are set, but **nobody has confirmed that the actual `claude` CLI honors them and emits traces** in the current release. This task closes that loop.

---

## Goal

Run a real anthive session and confirm in Langfuse that:

1. anthive's parent lifecycle span exists
2. Claude Code's own spans appear **nested under** the parent (proper trace context propagation)
3. Token counts and cost USD are populated on Claude Code spans
4. Resource attributes (`session.id`, `task.id`, `agent`, `mode`) are inherited by all child spans

If any of those are missing, document the gap and the likely cause (Claude Code env var rename, missing beta flag, OTLP version mismatch, etc.).

---

## Success criteria

- [ ] `T-20260504-langfuse-verify` is done (Langfuse receives traces)
- [ ] One real `anthive dispatch --local` session completes with telemetry enabled
- [ ] Langfuse Traces view shows the anthive parent span
- [ ] At least one Claude Code child span (e.g. `gen_ai.completion`, tool use, or whatever the current schema names them) appears nested inside the parent
- [ ] Child spans carry `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and a cost attribute (name TBD per current Claude Code schema)
- [ ] Resource attributes `session.id=<slug>`, `task.id=<id>`, `agent=<name>`, `mode=local` appear on the parent and propagate to children
- [ ] `docs/observability-runbook.md` gets a new section "Verifying Claude Code telemetry" with the actual span shape captured (paste a sample JSON trace)
- [ ] If anything is broken: file follow-up tasks `T-fix-otel-*.md` per gap, don't try to fix in this task

---

## Why this matters

The CLAUDE.md observability rules say: "Don't invent cost tracking. Claude Code's native OTEL exporter emits tokens + cost USD already. anthive emits *one parent lifecycle span* per session and lets Claude Code spans nest under it."

That sentence is an architectural commitment. If Claude Code's exporter has changed (env var renamed, beta flag retired, schema migrated to OpenTelemetry GenAI semconv stable), then anthive's cost reporting is silently wrong. Better to discover this against a smoke task than during a real workload.

---

## Implementation steps

1. **Confirm env vars are still current.** Run `claude --help` and grep for telemetry flags. Check the latest Claude Code release notes for any OTEL-related changes since the constants were written.
2. **Confirm beta flag is still required.** `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` may have graduated to GA or been replaced. Adjust if needed (file as separate fix task, don't inline).
3. **Dispatch a real session** with the smoke task. Watch the tmux pane to confirm Claude actually starts.
4. **In parallel, tail Langfuse ingestion.** Either watch the container logs (`docker logs -f anthive-langfuse`) or poll the Langfuse API for new traces.
5. **After session completes**, open Langfuse → Traces → find the slug. Click in.
6. **Capture the trace shape**: parent span name, children, attributes, links. Paste a redacted sample into the runbook.
7. **Verify trace context propagation.** Children should share the parent's `trace_id`. If they don't, the env vars aren't being inherited or Claude Code isn't reading them.
8. **Verify cost attribution.** Look for `gen_ai.usage.*` and any cost field. Document the actual attribute names (they may differ from what `langfuse_client.py` expects).
9. **Write up findings** in the runbook. Include both the happy path AND the failure modes you actually hit.

---

## Open questions to resolve during build

1. **Env var names current?** Are `CLAUDE_CODE_ENABLE_TELEMETRY` and `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA` still the active names, or have they been renamed in a recent Claude Code release?
2. **Beta flag still gating?** Or has enhanced telemetry graduated and the flag is a no-op (or required-to-NOT-be-set)?
3. **Span schema** — does Claude Code emit OpenTelemetry GenAI semantic conventions (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.*`) or its own custom namespace? If custom, does `langfuse_client.py` know about it?
4. **Cost attribute** — is cost emitted as `gen_ai.cost.usd`, `claude.cost_usd`, or computed by Langfuse from token counts + a pricing table? This determines whether `anthive status --json` cost values are real or fabricated.
5. **Trace context inheritance** — does `claude` CLI run inherit `OTEL_RESOURCE_ATTRIBUTES` from its env, or does it re-initialize and lose them? (Tmux + subprocess + Claude SDK is three layers — easy to drop attributes.)

---

## Anti-patterns

- **Don't fix bugs inline.** If Claude Code env vars are wrong, file `T-fix-otel-envvars.md` and stop. The point of verification is to enumerate what's broken, not to ship fixes mid-test.
- **Don't fake the trace.** If Claude Code isn't actually emitting, the test fails. Don't paper over it by emitting fake spans from anthive.
- **Don't skip the redacted-trace capture.** Future debugging will need to know what the spans looked like in May 2026.

---

## Do-not-touch list

- `anthive/observability.py` — read-only for this task
- `anthive/langfuse_client.py` — read-only for this task
- `swarm.toml` — only edit if endpoint changed during T-langfuse-verify
- `anthive/dispatchers/local.py` env block — flag drift goes in a follow-up task, not here

---

## Exit check

```bash
# Pre-req
docker ps --filter "name=anthive-langfuse" | grep -q Up || { echo "Langfuse not up"; exit 1; }

# Real session
anthive dispatch --local T-test-hello
anthive watch  # wait for READY-TO-MERGE

# Trace appears
curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "http://localhost:3000/api/public/traces?limit=5" | jq '.data[].name'
# → should include the session slug

# Runbook updated
grep -q "Verifying Claude Code telemetry" docs/observability-runbook.md && echo "✓ runbook section present"

# Sample trace captured
test -f docs/samples/trace-sample.json && echo "✓ sample trace saved"
```

Telemetry pipeline verified end-to-end. anthive cost numbers can now be trusted (or the gaps are filed as fix tasks).
