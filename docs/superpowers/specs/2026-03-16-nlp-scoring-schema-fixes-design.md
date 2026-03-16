# Design: NLP enrichment, scoring, and schema fixes

**Date:** 2026-03-16
**PR:** #39 (fix/idempotent-migrations — expanded scope)
**Status:** Approved

## Context

After deploying osint-core and running the austin-terror-watch plan, three systemic issues surfaced:

1. **Plan sync fails** — v2 schema has `additionalProperties: false` but never wired `enrichment` and `target_geo` as top-level properties (they exist in `$defs` but aren't referenced). One plan (cyber-threat-intel) is also mis-versioned as v1 while using v2 fields.
2. **NLP enrichment fields all null** — the inference endpoint moved from Ollama to vLLM but the code still calls Ollama's native API format. Celery also doesn't explicitly include the nlp_enrich module.
3. **Scoring shows no differentiation** — events cluster at ~0.465 because recency_half_life_hours is 12 but events average 510 hours old, and the DB plan version is missing target_geo/keywords (consequence of issue 1).

## Changes

### 1. Plan schema fixes

**`src/osint_core/schemas/plan-v2.schema.json`**

Add `enrichment` and `target_geo` as top-level properties referencing existing `$defs`:

```json
"enrichment": { "$ref": "#/$defs/enrichment" },
"target_geo": { "$ref": "#/$defs/target_geo" }
```

The definitions already exist at `$defs.enrichment` and `$defs.target_geo`. They just need `$ref` entries in the root `properties` object so `additionalProperties: false` doesn't reject them.

No changes to plan-v1.schema.json — no v1 plans require fields beyond what v1 defines.

**`plans/cyber-threat-intel.yaml`**

Bump `version: 1` to `version: 2`, add `plan_type: child` (no parent). The plan already has `sources`, `scoring`, and `notifications`, satisfying v2 child requirements. It uses `enrichment`, which is a v2-only field.

**`plans/austin-terror-watch.yaml`**

Change `recency_half_life_hours` from 12 to 168 (one week). At 12 hours, any event older than ~3 days floors at the 0.1 minimum recency factor, eliminating differentiation.

### 2. NLP enrichment — vLLM migration

**`src/osint_core/config.py`**

Replace Ollama-specific settings with generic LLM settings:

| Old | New | Default |
|-----|-----|---------|
| `ollama_url` (`OSINT_OLLAMA_URL`) | `llm_url` (`OSINT_LLM_URL`) | `http://vllm-inference.inference.svc.cluster.local:8000` |
| `ollama_model` (`OSINT_OLLAMA_MODEL`) | `llm_model` (`OSINT_LLM_MODEL`) | `meta-llama/Llama-3.2-3B-Instruct` |

**`src/osint_core/workers/nlp_enrich.py`**

Rewrite `_call_ollama` to `_call_llm` using the OpenAI-compatible chat completions API:

- Endpoint: `{settings.llm_url}/v1/chat/completions`
- Payload: OpenAI chat format with system message (analyst instructions) and user message (event data)
- Response parsing: `choices[0].message.content` instead of Ollama's `response` field
- Structured output: `response_format: {"type": "json_object"}`
- Same 10s timeout, same error handling, same retry logic

The prompt content stays identical — just restructured from a single `prompt` string into system/user message split.

All internal references renamed: `_call_ollama` to `_call_llm`, `settings.ollama_*` to `settings.llm_*`.

**`tests/workers/test_nlp_enrich.py`**

Update mocks to match:
- New URL path (`/v1/chat/completions` instead of `/api/generate`)
- New response format (OpenAI chat completions instead of Ollama native)

### 3. Celery configuration fix

**`src/osint_core/workers/celery_app.py`**

1. Add `"osint_core.workers.nlp_enrich"` to the `include` list
2. Add task route: `"osint_core.workers.nlp_enrich.*": {"queue": "enrich"}`

Routes NLP tasks to the `enrich` queue alongside vectorize/correlate. The existing `autodiscover_tasks` catches nlp_enrich by accident today, but explicit include + routing makes it reliable.

## File manifest

| # | File | Change type |
|---|------|-------------|
| 1 | `src/osint_core/schemas/plan-v2.schema.json` | Edit — add 2 `$ref` properties |
| 2 | `plans/cyber-threat-intel.yaml` | Edit — bump version, add plan_type |
| 3 | `plans/austin-terror-watch.yaml` | Edit — recency 12 to 168 |
| 4 | `src/osint_core/config.py` | Edit — replace ollama settings with llm settings |
| 5 | `src/osint_core/workers/nlp_enrich.py` | Edit — rewrite to OpenAI chat completions format |
| 6 | `src/osint_core/workers/celery_app.py` | Edit — add nlp_enrich include + route |
| 7 | `tests/workers/test_nlp_enrich.py` | Edit — update mocked URL and response format |

## Out of scope (post-deploy operational tasks)

- Patch DB plan v2 to add target_geo (run plan sync after deploy)
- Re-enrich 866 v1 events (bulk re-enrichment after deploy)
- Rescore all events (hit /rescore endpoint after deploy)
- FBI feed weight / GDELT query tightening (correct in YAML, needs sync)
