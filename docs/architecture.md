# Architecture

OSINT Core is an intelligence monitoring platform built on FastAPI, Celery, PostgreSQL, Redis, and Qdrant. It ingests data from configurable sources, enriches events with NLP and NER, scores them for relevance, and delivers alerts and digest reports through multiple notification channels.

## System Overview

The platform operates around **plans** -- versioned YAML configurations that define which sources to monitor, how to score and enrich events, and when to send notifications. Plans drive the Celery Beat schedule, meaning the entire ingest and reporting cadence is declarative.

Core capabilities:

- **Ingest** -- Fetch items from RSS feeds, xAI X search, university policy pages, and other connectors on a cron schedule.
- **Enrich** -- Run NLP classification (via vLLM), named entity recognition (via spaCy), and vector embedding (via sentence-transformers) on each event.
- **Score** -- Compute a 0.0-1.0 relevance score using keyword match, geographic proximity, source reputation, NLP classification, recency decay, and corroboration.
- **Correlate** -- Find related events via exact indicator overlap and semantic similarity (Qdrant cosine search).
- **Alert** -- Evaluate plan-defined alert rules and dispatch notifications through Gotify, Slack, email (SMTP), webhooks, or Resend.
- **Report** -- Compile periodic digests and prospecting reports with PDF rendering (WeasyPrint) and MinIO archival.
- **Retain** -- Purge expired events based on retention class (ephemeral: 30 days, standard: 1 year, evidentiary: never).

## Service Topology

From `docker-compose.dev.yaml`, the local development stack consists of six services:

| Service    | Image / Target         | Ports              | Purpose                                      |
|------------|------------------------|--------------------|----------------------------------------------|
| `postgres` | `postgres:16`          | 5432               | Primary relational store (events, plans, leads, alerts, briefs, audit) |
| `redis`    | `redis:7-alpine`       | 6379               | Rate-limit state (db 0), Celery broker (db 1), Celery result backend (db 2) |
| `qdrant`   | `qdrant/qdrant:latest` | 6333, 6334         | Vector store for event embeddings and semantic search |
| `api`      | Dockerfile target `api`| 8000               | FastAPI application server                    |
| `worker`   | Dockerfile target `worker` | --             | Celery worker processes (all queues)          |
| `beat`     | Dockerfile target `beat`   | --             | Celery Beat scheduler (plan-driven + static)  |

Additional production dependencies (not in compose):

- **Groq** -- LLM API (gpt-oss-20b) for NLP enrichment, narrative generation, and deep analysis. Configured via `OSINT_LLM_PROVIDER=groq`. Uses strict structured output for NLP/narrative tasks and `json_object` response mode for deep analysis of large documents.
- **vLLM** -- Fallback LLM inference server (`OSINT_VLLM_URL`), used when Groq returns 429/5xx errors. Selectable via `OSINT_LLM_PROVIDER=vllm`.
- **MinIO** -- Object storage for PDF archival (briefs and prospecting reports).
- **Resend** -- Transactional email API for prospecting report delivery.
- **CourtListener** -- Legal citation verification API.

## Request Flow

```
Client Request
    |
    v
FastAPI (main.py)
    |-- RateLimitMiddleware (Redis-backed fixed-window)
    |-- OpenTelemetry instrumentation (when OSINT_OTEL_ENDPOINT is set)
    |-- ProblemError exception handler (RFC 7807)
    |
    v
Router (src/osint_core/api/routes/*)
    |-- health, plan, events, indicators, entities, alerts,
    |   briefs, search, jobs, audit, watches, leads, preferences
    |
    v
Service Layer (src/osint_core/services/*)
    |
    v
Database (async SQLAlchemy + asyncpg, NullPool)
```

The database session factory is defined in `src/osint_core/db.py` using `create_async_engine` with `NullPool` and `expire_on_commit=False`. All database access uses `postgresql+asyncpg://` URIs.

## Ingest Pipeline

The ingest pipeline is the primary data flow through the system:

```
Celery Beat (plan-driven cron schedule)
    |
    v
osint.ingest_source (ingest queue)
    |-- Resolve plan + source config from PlanStore
    |-- Fetch items via connector registry (RSS, xAI, etc.)
    |-- Deduplicate via SHA-256 fingerprint (plan_id + source_id + item data)
    |-- Extract indicators (CVEs, IPs, domains, URLs, hashes)
    |-- Persist Event + Indicator rows
    |-- Record Job status
    |
    v
Enrichment Chain (per event):
    osint.nlp_enrich_event (enrich queue)
        |
        v
    Parallel group:
        osint.score_event (score queue)
        osint.vectorize_event (enrich queue)
        osint.enrich_entities (enrich queue)
        |
        v
    osint.correlate_event (enrich queue)
```

For CAL prospecting plans, the enrichment chains are wrapped in a Celery chord so that `osint.match_leads` fires only after all enrichment completes, avoiding race conditions with partial data.

### Deep Analysis Stage

After lead matching, CAL plans run an additional deep analysis stage before report generation:

```
osint.match_leads (enrich queue)
    |
    v
osint.analyze_leads (enrich queue)
    |-- Retrieve full policy documents from MinIO
    |-- Extract text from HTML and PDF (via PyMuPDF) sources
    |-- Chunk large documents at 20k characters
    |-- Send chunks to Groq (gpt-oss-20b) for clause-level constitutional analysis
    |-- Match precedent via CourtListener landmark case lookup
    |-- Store results in Lead.deep_analysis JSONB field
    |-- Filter non-actionable leads from downstream reports
    |
    v
osint.generate_prospecting_report (osint queue)
```

## Workers

All workers are registered in `src/osint_core/workers/celery_app.py`. Tasks use `asyncio.new_event_loop()` to bridge sync Celery with async database and HTTP calls.

| Worker File | Celery Task(s) | Purpose |
|---|---|---|
| `ingest.py` | `osint.ingest_source` | Fetch items from a plan source, deduplicate, persist events and indicators, dispatch enrichment chains |
| `enrich.py` | `osint.vectorize_event`, `osint.semantic_search`, `osint.correlate_event` | Embed event text into Qdrant (384-dim, all-MiniLM-L6-v2), run semantic similarity search, find correlated events via indicator overlap and vector similarity |
| `nlp_enrich.py` | `osint.nlp_enrich_event` | Call LLM (Groq or vLLM, per `OSINT_LLM_PROVIDER`) for summary, relevance classification, entity extraction, and ATT&CK technique or constitutional-rights classification (CAL mode) |
| `score.py` | `osint.score_event`, `osint.rescore_all_events` | Compute relevance score (keyword + geo + source trust + NLP + recency + corroboration), map to severity, apply promotion rules, create alerts and chain notifications |
| `notify.py` | `osint.send_notification` | Dispatch alerts via Gotify, Slack, webhook, or email (SMTP with Jinja2 HTML templates); supports PDF attachments from MinIO |
| `digest.py` | `osint.compile_digest` | Aggregate events by time window (daily/weekly/shift), persist Brief record, optionally generate PDF and chain email notification |
| `prospecting.py` | `osint.match_leads`, `osint.generate_prospecting_report`, `osint.collect_prospecting_sources` | Match enriched events to leads with confidence scoring; generate PDF prospecting reports with narrative sections and legal citation verification (CourtListener); email via Resend; trigger source collection |
| `deep_analysis.py` | `osint.analyze_leads` | Retrieve policy documents from MinIO, extract text (HTML/PDF via PyMuPDF), chunk at 20k chars, run clause-level constitutional analysis via Groq (gpt-oss-20b), match precedent via CourtListener, store results in `Lead.deep_analysis` JSONB, filter non-actionable leads |
| `retention.py` | `osint.purge_expired_events` | Delete events past retention threshold (ephemeral: 30d, standard: 365d), clean up Qdrant vectors, write audit log |
| `k8s_dispatch.py` | `osint.enrich_entities` | Extract named entities via spaCy NER (PERSON, ORG, GPE, PRODUCT, LOC), upsert Entity records, link to events; future: K8s GPU job dispatch |

### Queue Routing

Tasks are routed to dedicated queues via `task_routes` in `celery_app.py`:

| Queue     | Tasks |
|-----------|-------|
| `ingest`  | `osint.ingest_source`, `osint.collect_prospecting_sources` |
| `enrich`  | `osint.vectorize_event`, `osint.semantic_search`, `osint.correlate_event`, `osint.enrich_entities`, `osint.nlp_enrich_event`, `osint.match_leads`, `osint.analyze_leads` |
| `score`   | `osint.score_event`, `osint.rescore_all_events` |
| `notify`  | `osint.send_notification` |
| `digest`  | `osint.compile_digest` |
| `osint`   | `osint.generate_prospecting_report`, `osint.purge_expired_events` (default queue) |

### Beat Schedule

Static entries (always active):

| Entry | Task | Schedule |
|---|---|---|
| `purge-expired-events-daily` | `osint.purge_expired_events` | Daily at 03:00 America/Chicago |
| `collect-prospecting-sources` | `osint.collect_prospecting_sources` | 07:00 and 14:00 America/Chicago |
| `generate-prospecting-report` | `osint.generate_prospecting_report` | 08:00 and 15:00 America/Chicago |

Plan-driven entries are loaded dynamically by `PlanScheduler` (a custom `PersistentScheduler` subclass). It calls `PlanEngine.build_beat_schedule()` for each active plan, converting source `schedule_cron` fields into Celery Beat entries that dispatch `osint.ingest_source`.

## Services

| Service | File | Purpose |
|---|---|---|
| Scoring | `services/scoring.py` | Compute event relevance scores using keyword match, geographic proximity, source reputation, NLP classification, recency decay, and corroboration bonus. `ScoringConfig` dataclass, `score_event()`, `score_to_severity()`, `match_keywords()` |
| Correlation | `services/correlation.py` | Find correlated events via exact indicator overlap and semantic similarity. `find_correlated_events()`, `correlate_exact()`, `is_semantic_duplicate()` |
| Deduplication | `services/dedup.py` | Near-duplicate detection using SimHash (64-bit, 3-shingle). `compute_simhash()`, `simhash_distance()`, `normalize_title()` |
| Vectorization | `services/vectorize.py` | Embed text with sentence-transformers (all-MiniLM-L6-v2, 384-dim), upsert/search Qdrant. `embed_text()`, `upsert_event()`, `search_similar()`, `get_qdrant()` |
| NER | `services/ner.py` | Named entity recognition via spaCy (en_core_web_sm). Extracts PERSON, ORG, GPE, PRODUCT, LOC. `extract_entities()` |
| Alerting | `services/alerting.py` | Alert creation logic: fingerprint dedup, threshold decisions, quiet-hours checking, severity escalation. `compute_fingerprint()`, `should_alert()`, `check_quiet_hours()`, `should_escalate()` |
| Alert Rules | `services/alert_rules.py` | Parse and evaluate alert rules from plan YAML. `AlertRule` dataclass, `evaluate_rules()`, `parse_rules_from_plan()` |
| Notification | `services/notification.py` | Route matching by severity threshold and message formatting. `NotificationService`, `NotificationRoute` |
| Resend Notifier | `services/resend_notifier.py` | Send PDF reports via Resend email API with HTML body and base64-encoded attachment. `ResendNotifier.send_report()` |
| Brief Generator | `services/brief_generator.py` | Generate intelligence briefs via LLM (Groq or vLLM) or Jinja2 template fallback. `BriefGenerator.generate()`, `fetch_brief_context()` (Postgres full-text search) |
| Indicators | `services/indicators.py` | Regex-based IOC extraction and normalization for CVEs, domains, IPs, URLs, SHA-256/MD5 hashes. `extract_indicators()`, `normalize_indicator()` |
| Lead Matcher | `services/lead_matcher.py` | Deduplicate events into leads with confidence scoring, fingerprinting (incident vs. policy), and source citation tracking. `LeadMatcher.match_event_to_lead()`, `compute_confidence()` |
| Watch Matcher | `services/watch_matcher.py` | Evaluate whether events match active watches by geography (country code, bounding box), keywords, and severity threshold. `matches_watch()` |
| Plan Engine | `services/plan_engine.py` | Validate plan YAML against JSON Schema (v1/v2), scan for embedded secrets, compute content hashes, build Celery Beat schedules from source cron expressions. `PlanEngine` |
| Plan Store | `services/plan_store.py` | Versioned plan CRUD via async SQLAlchemy. `PlanStore` with `store_version()`, `get_active()`, `activate()`, `rollback()`, `get_next_version()` |
| Prospecting Report | `services/prospecting_report.py` | Orchestrate lead selection, LLM narrative generation (Groq or vLLM), CourtListener citation verification, WeasyPrint PDF rendering, and MinIO archival. `ProspectingReportGenerator.generate_report()` |
| PDF Export | `services/pdf_export.py` | Render markdown to styled PDF via WeasyPrint, upload to MinIO. `render_brief_pdf()`, `upload_pdf_to_minio()`, `generate_and_upload_pdf()` |
| CourtListener | `services/courtlistener.py` | Async client for CourtListener Citation Lookup API with rate limiting. `CourtListenerClient.verify_citations()` returns `VerifiedCitation` objects |
| Deep Analyzer | `services/deep_analyzer.py` | Orchestrate deep analysis of leads: retrieve policy documents from MinIO, delegate text extraction and chunking, send to Groq for clause-level constitutional analysis, match precedent via CourtListener, persist results to `Lead.deep_analysis` JSONB. `DeepAnalyzer.analyze()` |
| Document Extractor | `services/document_extractor.py` | Extract text from HTML and PDF documents (PyMuPDF for PDF, html-to-text for HTML), chunk large documents at 20k character boundaries. `DocumentExtractor.extract()`, `DocumentExtractor.chunk()` |
| Geo | `services/geo.py` | Geographic lookup from static JSON data: ISO2-to-ISO3 conversion, country lookup by code or name, region resolution. `lookup_country()`, `lookup_gpe()`, `get_region()` |
| Audit | `services/audit.py` | Append-only audit logging via `AuditLog` model. `create_audit_entry()`, `list_audit_entries()` |

## Infrastructure

### Database

- **Engine**: SQLAlchemy async with `asyncpg` driver (`src/osint_core/db.py`)
- **Pool**: `NullPool` (connection-per-request; suited for serverless and worker environments)
- **Session**: `async_sessionmaker` with `expire_on_commit=False`
- **Migrations**: Alembic with `asyncpg` driver (see `migrations/`)
- **URI format**: `postgresql+asyncpg://...` (required by the async driver)

### Logging

- **Library**: structlog (`src/osint_core/logging.py`)
- **Output**: JSON via `JSONRenderer`
- **Processors**: context variable merging, log level, stack info, exception info, ISO timestamps
- **Filtering**: Configurable via `log_level` parameter (default: INFO)

### Metrics

- **Library**: prometheus_client (`src/osint_core/metrics.py`)
- **Custom metrics**:
  - `osint_events_ingested_total` (Counter, by source_id)
  - `osint_alerts_fired_total` (Counter, by severity and route)
  - `osint_ingestion_duration_seconds` (Histogram, by source_id)
  - `osint_active_jobs` (Gauge, by job_type)
  - `osint_celery_queue_depth` (Gauge, by queue)

### Tracing

- **Library**: OpenTelemetry (`src/osint_core/tracing.py`)
- **Exporter**: OTLP gRPC (configured via `OSINT_OTEL_ENDPOINT`)
- **Sampling**: `TraceIdRatioBased` with configurable `OSINT_OTEL_SAMPLE_RATE`
- **Instrumentation**: FastAPI (via `FastAPIInstrumentor`) and Celery (via `CeleryInstrumentor`, initialized per worker process on `worker_process_init` signal)
- **No-op**: Tracing is disabled when `OSINT_OTEL_ENDPOINT` is empty (the default)

### Celery Configuration

- **Broker**: Redis (db 1)
- **Result backend**: Redis (db 2)
- **Serialization**: JSON
- **Timezone**: America/Chicago (UTC enabled)
- **Reliability**: `task_acks_late=True`, `worker_prefetch_multiplier=1`, `task_track_started=True`
- **Default queue**: `osint`
- **Retry strategy**: Exponential backoff with cap (typically `min(2^retries * 30, 900)` seconds)
