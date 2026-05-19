---
id: T-20260504-langfuse-verify
title: "Verify self-hosted Langfuse stack ingests anthive OTEL traces end-to-end"
status: ready
effort: S
budget_usd: 0
agent: python-developer
depends_on: []
touches_paths:
  - docs/observability-runbook.md
  - docker/langfuse-compose.yml
created: 2026-05-04T00:00:00-0300
tags: ["observability", "verification", "langfuse"]
---

# T-20260504-langfuse-verify — Langfuse stack verification

> **Why:** the compose file at `docker/langfuse-compose.yml` and the OTEL endpoint config in `swarm.toml` have never been exercised against a running Langfuse instance. Before we dogfood anthive on real tasks, we need to know the observability stack actually receives, parses, and renders traces from anthive sessions. This task is **operational verification, not new code**.

---

## Goal

Stand up Langfuse via the existing compose file, route a real anthive session's OTEL traffic to it, and confirm traces appear in the UI with the expected resource attributes (`session.id`, `task.id`, `agent`, `mode`).

Document every rough edge in `docs/observability-runbook.md` so future operators can repeat this in 5 minutes instead of 50.

---

## Success criteria

- [ ] `docker compose -f docker/langfuse-compose.yml up -d` starts both containers and they reach healthy state
- [ ] Langfuse UI loads at `http://localhost:3000`
- [ ] Local account, org, and project named `anthive` are created and documented
- [ ] `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` retrieval flow is documented
- [ ] OTEL ingest endpoint (`http://localhost:3000/api/public/otel/v1/traces`) responds (any non-connection-refused response counts — we just need to know it's reachable)
- [ ] `anthive/langfuse_client.py` can authenticate against the local instance (write a one-liner script that lists projects or fetches health)
- [ ] At least one anthive parent lifecycle span (emitted by `anthive/observability.py`) appears in the Langfuse Traces view
- [ ] The trace shows the expected resource attributes: `session.id`, `task.id`, `agent`, `mode=local`
- [ ] `docs/observability-runbook.md` exists with: prerequisites, start/stop commands, first-time setup, key retrieval, smoke test, common failure modes

---

## Why this matters

The CLAUDE.md observability rules state Langfuse is "self-hosted by default" and that the dispatcher injects OTEL env vars. Both pieces are coded but neither has been verified live. If the compose file's image tag drifts (Langfuse v2 → v3 schema changed), or the OTEL ingestion path changed, we'll discover it here, not during a paying customer's first run.

Also: this is the prerequisite for `T-20260504-otel-verify`. That task only makes sense if Langfuse can receive traces.

---

## Implementation steps

1. Run `docker compose -f docker/langfuse-compose.yml up -d`. Watch logs for ~60s. Note any image-pull or migration failures.
2. Open `http://localhost:3000`. Walk through the new-account flow. Capture screenshots or step-by-step instructions in the runbook.
3. Create org + project. Generate API keys. Save to `.env` (gitignored).
4. Verify the OTEL ingest endpoint responds. Common URL patterns:
   - `/api/public/otel/v1/traces` (current Langfuse v3)
   - `/api/public/ingestion` (older path)
   Confirm which one Langfuse v3 actually serves and update `swarm.toml` if wrong.
5. Write a tiny smoke script (`scripts/langfuse_smoke.py`) that:
   - Loads keys from env
   - Hits `langfuse_client.py` health endpoint
   - Emits a single test span via `anthive/observability.py`
   - Polls Langfuse API for that trace
6. Run an actual `anthive dispatch --local` against the throwaway smoke task (`tasks/T-test-hello.md` if present, or create one).
7. Open Langfuse UI. Find the trace. Verify resource attributes are present and correct.
8. Document everything in `docs/observability-runbook.md`.

---

## Open questions to resolve during build

1. **Langfuse v3 OTEL endpoint path** — the compose file uses `langfuse/langfuse:3` but the env var `OTEL_EXPORTER_OTLP_ENDPOINT_ENABLED: "true"` syntax may not match v3's expected config. Verify against current Langfuse docs.
2. **OTLP protocol** — does anthive emit HTTP/protobuf or HTTP/JSON? Does Langfuse v3 accept both? The `opentelemetry-exporter-otlp-proto-http` package suggests protobuf, but confirm.
3. **Cost mapping** — once Claude Code spans appear nested under our parent span, does Langfuse auto-extract `gen_ai.usage.*` attributes into its cost view? Or do we need a model-pricing config?
4. **Project scoping** — does the public/secret key pair scope ingestion to one project, or do we need to set a project header?
5. **Self-signed certs / localhost SSL** — is `http://` (not https) accepted by the OTEL exporter without disabling TLS verification?

---

## Anti-patterns

- **Don't write new instrumentation code.** This task is verification of existing code. If something is broken, file a follow-up task — don't fix it inline (unless it's a one-line config drift like a wrong port).
- **Don't skip the runbook.** The whole point is leaving behind a repeatable procedure. Verbal confirmation that "it worked on my machine" is not a deliverable.
- **Don't commit `.env` or any keys.** Even local Langfuse keys.

---

## Do-not-touch list

- `anthive/observability.py` — already implemented; this task verifies it, doesn't change it
- `anthive/langfuse_client.py` — same
- `anthive/dispatchers/local.py` OTEL env block ([lines 336-340](anthive/dispatchers/local.py#L336-L340)) — same
- `swarm.toml` — only edit if endpoint path is provably wrong

---

## Exit check

```bash
# Stack up
docker compose -f docker/langfuse-compose.yml up -d
docker ps --filter "name=anthive-langfuse"
# → both containers Up, db healthy

# Keys loaded
set -a; source .env; set +a
echo $LANGFUSE_PUBLIC_KEY  # → pk-lf-...

# Smoke trace lands
python scripts/langfuse_smoke.py
# → prints "✓ trace <id> visible in Langfuse"

# Real session emits a real trace
anthive dispatch --local T-test-hello
# After session completes, open http://localhost:3000
# → see trace with session.id=T-test-hello, agent=python-developer, mode=local

# Runbook exists
test -f docs/observability-runbook.md && echo "✓ runbook present"
```

Observability backend verified. We can now trust dashboards.
