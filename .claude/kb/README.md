# ACT Knowledge Base

> The structured knowledge layer that grounds every agent response for the
> **Agent Context Protocol** research benchmark.

**16 domains | MCP-validated 2026-04-20**

---

## How KB Works — KB-First Architecture

Every agent follows **KB-First Resolution**: local knowledge is always checked
before external sources. This is mandatory, not optional.

### Resolution Order

```text
1. KB CHECK        Agent reads index.md of the relevant domain (headings only)
2. ON-DEMAND LOAD  Agent reads specific concept or pattern file matching the task
3. MCP FALLBACK    Only if KB content is insufficient (max 3 MCP calls)
4. CONFIDENCE      Calculated from evidence matrix, never self-assessed
```

The machine-readable registry of every domain is [`_index.yaml`](./_index.yaml)
(current version: `3.0`).

---

## Domain Catalog

### ACT Research Core (new — 2026-04-20)

| Domain                | Purpose                                                                                 |
|-----------------------|-----------------------------------------------------------------------------------------|
| `act-protocol`        | The ACT specification — two-layer (ACT-P + ACT-R), six principles, canonical scoreboard |
| `agent-reading-layer` | ACT-R deep dive — six card types, grammar-vs-filters, token budget                      |
| `benchmarking`        | LLM benchmark methodology — fair evaluation, reproducibility, token accounting          |
| `duckdb`              | DuckDB for the ACT benchmark — SQL dialect, EXPLAIN plans, Parquet I/O, Postgres attach |
| `research-writing`    | Academic writing — paper structure, claim-evidence links, reproducibility checklist     |

### Retained General-Purpose

| Domain              | Purpose                                                                              |
|---------------------|--------------------------------------------------------------------------------------|
| `data-modeling`     | Dimensional, Data Vault, SCD, OBT, schema evolution                                 |
| `data-quality`      | Contracts, observability, Soda, Great Expectations, dbt tests                       |
| `sql-patterns`      | Cross-dialect SQL — window functions, CTEs, deduplication                           |
| `lakehouse`         | Open table formats and catalogs — Iceberg, Delta, DuckLake                          |
| `medallion`         | Bronze/Silver/Gold (context for `model_gold` comparison)                            |
| `modern-stack`      | DuckDB, Polars, SQLMesh, Evidence.dev (local-first analytics)                       |
| `prompt-engineering`| Chain-of-thought, structured extraction, few-shot, system prompts                   |
| `genai`             | Multi-agent systems, RAG, state machines, tool calling, guardrails                  |
| `pydantic`          | BaseModel, validators, LLM output validation                                        |
| `python`            | Dataclasses, type hints, generators, async, project structure                       |
| `testing`           | pytest, fixtures, mocking, parametrize, integration tests                           |

---

## Agent-to-Primary-KB Mapping

### Research Agents (new — `.claude/agents/research/`)

| Agent                         | Primary KB domains                                      |
|-------------------------------|---------------------------------------------------------|
| `benchmark-harness-engineer`  | `benchmarking`, `act-protocol`, `duckdb`, `python`      |
| `llm-evaluator-designer`      | `benchmarking`, `duckdb`, `testing`                     |
| `duckdb-specialist`           | `duckdb`, `sql-patterns`, `benchmarking`                |
| `schema-card-author`          | `agent-reading-layer`, `act-protocol`, `prompt-engineering` |
| `paper-writer`                | `research-writing`, `act-protocol`, `benchmarking`      |
| `results-analyst`             | `benchmarking`, `research-writing`, `act-protocol`      |

### Architect / Data / Test / Dev / Python / Workflow

| Agent                    | Primary KB domains                                  |
|--------------------------|-----------------------------------------------------|
| `schema-designer`        | `data-modeling`, `lakehouse`                        |
| `lakehouse-architect`    | `lakehouse`, `data-modeling`, `duckdb`              |
| `medallion-architect`    | `medallion`, `data-modeling`                        |
| `genai-architect`        | `genai`, `prompt-engineering`, `agent-reading-layer`|
| `ai-data-engineer`       | `genai`, `prompt-engineering`, `data-quality`       |
| `sql-optimizer`          | `sql-patterns`, `data-modeling`, `duckdb`           |
| `data-quality-analyst`   | `data-quality`, `data-modeling`, `testing`          |
| `data-contracts-engineer`| `data-quality`, `data-modeling`                     |
| `test-generator`         | `data-quality`, `testing`, `python`                 |
| `code-reviewer`          | `data-quality`, `sql-patterns`, `python`            |
| `python-developer`       | `python`, `pydantic`                                |
| `llm-specialist`         | `prompt-engineering`, `pydantic`                    |
| `ai-prompt-specialist`   | `prompt-engineering`                                |
| `codebase-explorer`      | (none — read-only)                                  |
| `workflow/*`             | (cross-cutting)                                     |

---

## Templates

All under [`_templates/`](./_templates/):

- `concept.md.template` — for `concepts/*.md` (≤150 lines)
- `pattern.md.template` — for `patterns/*.md` (≤200 lines)
- `index.md.template` — for domain `index.md`
- `quick-reference.md.template` — for domain `quick-reference.md` (≤100 lines)
- `spec.yaml.template` — for `specs/*.yaml`
- `test-case.json.template` — for test fixtures
- `domain-manifest.yaml.template` — for new-domain bootstrap

Size limits are enforced from [`_index.yaml`](./_index.yaml) (`limits` block).

---

## Shared Resources

- [`shared/anti-patterns.md`](./shared/anti-patterns.md) — Cross-agent
  anti-pattern library, referenced by every agent's `anti_pattern_refs`.

---

## History

**2026-04-20 — ACT Refocus.** Removed 12 out-of-scope domains (`airflow`,
`aws`, `cloud-platforms`, `dbt`, `gcp`, `lakeflow`, `microsoft-fabric`,
`spark`, `streaming`, `supabase`, `terraform`, `ai-data-engineering`).
Added 5 ACT-research-core domains (`act-protocol`, `agent-reading-layer`,
`benchmarking`, `duckdb`, `research-writing`). See `changelog.md` at the
repo root.
