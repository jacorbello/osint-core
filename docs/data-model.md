# Data Model

This document describes the SQLAlchemy ORM models and Pydantic API schemas that make up the osint-core data layer. All tables live in the `osint` PostgreSQL schema and are accessed through the `asyncpg` driver.

---

## Base Classes

Defined in `src/osint_core/models/base.py`.

All models inherit from a shared `DeclarativeBase` with a metadata object scoped to the `osint` Postgres schema. Two mixins provide common columns:

### UUIDMixin

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | `UUID` | No | Primary key, default `uuid4` |

### TimestampMixin

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `created_at` | `TIMESTAMP` | No | Server-default `now()` |

Every model listed below uses both mixins unless noted otherwise.

---

## Common Schema Types

Defined in `src/osint_core/schemas/common.py`.

Several enums and base classes are shared across API schemas:

| Type | Values / Purpose |
|------|-----------------|
| `SeverityEnum` | `info`, `low`, `medium`, `high`, `critical` |
| `StatusEnum` | `open`, `acked`, `escalated`, `resolved` |
| `JobStatusEnum` | `queued`, `running`, `succeeded`, `failed`, `partial_success`, `dead_letter` |
| `RetentionClassEnum` | `ephemeral`, `standard`, `evidentiary` |
| `PageInfo` | Offset pagination metadata (`offset`, `limit`, `total`, `has_more`) |
| `CollectionResponse` | Generic paginated wrapper (contains `page: PageInfo`) |
| `ProblemDetails` | RFC 7807 error payload with `FieldError` list |

---

## Models

### Event

**File:** `src/osint_core/models/event.py`
**Table:** `osint.events`

An ingested OSINT event — the central record that links to entities, indicators, and artifacts.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK (from UUIDMixin) |
| `created_at` | TIMESTAMP | No | Server-default `now()` (from TimestampMixin) |
| `event_type` | Text | No | Classification of the event |
| `source_id` | Text | No | Identifier from the originating source |
| `title` | Text | Yes | Human-readable title |
| `summary` | Text | Yes | Short summary |
| `raw_excerpt` | Text | Yes | Raw text from the source |
| `occurred_at` | TIMESTAMP(tz) | Yes | When the event happened |
| `ingested_at` | TIMESTAMP(tz) | No | Server-default `now()` |
| `score` | Float | Yes | Relevance or threat score |
| `severity` | Text | Yes | Constrained to `info`, `low`, `medium`, `high`, `critical` |
| `latitude` | Float | Yes | Geographic latitude |
| `longitude` | Float | Yes | Geographic longitude |
| `country_code` | Text | Yes | ISO country code |
| `region` | Text | Yes | Geographic region |
| `source_category` | Text | Yes | Category of the source |
| `actors` | JSONB | Yes | Structured actor data |
| `event_subtype` | Text | Yes | Finer-grained event classification |
| `dedupe_fingerprint` | Text | No | Unique deduplication hash |
| `plan_version_id` | UUID (FK) | Yes | References `osint.plan_versions.id` |
| `metadata` | JSONB | No | Arbitrary key-value metadata (mapped as `metadata_`) |
| `simhash` | BigInteger | Yes | Near-duplicate detection hash (indexed) |
| `canonical_event_id` | UUID (FK) | Yes | Self-referencing FK to canonical event |
| `corroboration_count` | Integer | No | Default `0`; number of corroborating sources |
| `nlp_relevance` | Text | Yes | NLP-assigned relevance label |
| `nlp_summary` | Text | Yes | NLP-generated summary |
| `fatalities` | Integer | Yes | Reported fatality count |
| `search_vector` | TSVECTOR | Yes | Computed full-text search column (persisted) |

#### Relationships

- `plan_version` -> `PlanVersion` (many-to-one, selectin)
- `entities` -> `Entity` (many-to-many via `event_entities`)
- `indicators` -> `Indicator` (many-to-many via `event_indicators`)
- `artifacts` -> `Artifact` (many-to-many via `event_artifacts`)

#### Indexes

- `ix_events_dedupe_fingerprint` (unique)
- `ix_events_source_id_ingested_at` (composite, `ingested_at` descending)
- `ix_events_score_desc` (descending, nulls last)
- `ix_events_search_vector` (GIN)
- `ix_events_country_code`, `ix_events_region`, `ix_events_source_category`

#### Association Tables

| Table | Columns | Description |
|-------|---------|-------------|
| `event_entities` | `event_id`, `entity_id` | Links events to entities (CASCADE delete) |
| `event_indicators` | `event_id`, `indicator_id` | Links events to indicators (CASCADE delete) |
| `event_artifacts` | `event_id`, `artifact_id` | Links events to artifacts (CASCADE delete) |

#### Pydantic Schemas (`src/osint_core/schemas/event.py`)

| Class | Purpose |
|-------|---------|
| `EventResponse` | Read serialization; aliases `metadata_` to `metadata` |
| `EventList` | Paginated collection of `EventResponse` |
| `EventSearchList` | Extends `EventList` with `retrieval_mode` field |

---

### Indicator

**File:** `src/osint_core/models/indicator.py`
**Table:** `osint.indicators`

A threat indicator such as an IP address, domain, hash, or other observable.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `indicator_type` | Text | No | Kind of indicator (IP, domain, hash, etc.) |
| `value` | Text | No | The indicator value |
| `confidence` | Float | No | Default `0.5`; confidence score |
| `first_seen` | TIMESTAMP(tz) | No | Server-default `now()` |
| `last_seen` | TIMESTAMP(tz) | No | Server-default `now()` |
| `sources` | ARRAY(Text) | No | List of source identifiers |
| `metadata` | JSONB | No | Arbitrary metadata (mapped as `metadata_`) |

#### Constraints

- Unique on (`indicator_type`, `value`)

#### Pydantic Schemas (`src/osint_core/schemas/indicator.py`)

| Class | Purpose |
|-------|---------|
| `IndicatorResponse` | Read serialization; aliases `metadata_` to `metadata` |
| `IndicatorList` | Paginated collection of `IndicatorResponse` |

---

### Entity

**File:** `src/osint_core/models/entity.py`
**Table:** `osint.entities`

A named entity extracted from OSINT events (person, organization, infrastructure, etc.).

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `entity_type` | Text | No | Category (person, org, etc.) |
| `name` | Text | No | Primary name |
| `aliases` | ARRAY(Text) | No | Alternative names |
| `attributes` | JSONB | No | Structured attributes |
| `first_seen` | TIMESTAMP(tz) | No | Server-default `now()` |
| `last_seen` | TIMESTAMP(tz) | No | Server-default `now()` |

#### Indexes

- `ix_entities_name_fts` (GIN with `gin_trgm_ops` on `name`)

#### Pydantic Schemas (`src/osint_core/schemas/entity.py`)

| Class | Purpose |
|-------|---------|
| `EntityResponse` | Read serialization |
| `EntityList` | Paginated collection of `EntityResponse` |

---

### Alert

**File:** `src/osint_core/models/alert.py`
**Table:** `osint.alerts`

An alert raised by the scoring or correlation engine.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `fingerprint` | Text | No | Deduplication fingerprint |
| `severity` | Text | No | Alert severity |
| `title` | Text | No | Human-readable title |
| `summary` | Text | Yes | Longer description |
| `event_ids` | ARRAY(UUID) | No | Related event IDs |
| `indicator_ids` | ARRAY(UUID) | No | Related indicator IDs |
| `entity_ids` | ARRAY(UUID) | No | Related entity IDs |
| `route_name` | Text | Yes | Notification route |
| `status` | Text | No | Default `open`; constrained to `open`, `acked`, `escalated`, `resolved` |
| `occurrences` | Integer | No | Default `1`; count of matching firings |
| `first_fired_at` | TIMESTAMP(tz) | No | Server-default `now()` |
| `last_fired_at` | TIMESTAMP(tz) | No | Server-default `now()` |
| `acked_at` | TIMESTAMP(tz) | Yes | When acknowledged |
| `acked_by` | Text | Yes | Who acknowledged |
| `plan_version_id` | UUID (FK) | Yes | References `osint.plan_versions.id` |

#### Relationships

- `plan_version` -> `PlanVersion` (many-to-one, selectin)

#### Indexes

- `ix_alerts_fingerprint_last_fired` (composite, `last_fired_at` descending)

#### Pydantic Schemas (`src/osint_core/schemas/alert.py`)

| Class | Purpose |
|-------|---------|
| `AlertResponse` | Read serialization |
| `AlertList` | Paginated collection of `AlertResponse` |
| `AlertUpdateRequest` | Update alert lifecycle status |

---

### Artifact

**File:** `src/osint_core/models/artifact.py`
**Table:** `osint.artifacts`

A stored artifact such as a screenshot, HTML snapshot, or PDF capture.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `artifact_type` | Text | No | Kind of artifact |
| `minio_uri` | Text | Yes | Object storage URI |
| `minio_version_id` | Text | Yes | Object storage version |
| `sha256` | Text | Yes | Content hash |
| `capture_tool` | Text | Yes | Tool used for capture |
| `source_url` | Text | Yes | Original URL |
| `final_url` | Text | Yes | Final URL after redirects |
| `http_status` | Integer | Yes | HTTP response code |
| `retention_class` | Text | No | Default `standard` |
| `plan_version_id` | UUID (FK) | Yes | References `osint.plan_versions.id` |
| `case_id` | UUID | Yes | Optional case reference |

#### Relationships

- `plan_version` -> `PlanVersion` (many-to-one, selectin)

#### Pydantic Schemas

No dedicated schema file. Artifacts are accessed through event relationships.

---

### AuditLog

**File:** `src/osint_core/models/audit.py`
**Table:** `osint.audit_log`

Immutable audit trail recording user and system actions.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `action` | Text | No | Action identifier |
| `actor` | Text | Yes | Actor identifier (e.g., Keycloak sub) |
| `actor_username` | Text | Yes | Human-readable username |
| `actor_roles` | ARRAY(Text) | Yes | Roles held at time of action |
| `resource_type` | Text | Yes | Type of affected resource |
| `resource_id` | Text | Yes | ID of affected resource |
| `details` | JSONB | No | Arbitrary action details |

#### Indexes

- `ix_audit_log_created_at_desc` (descending on `created_at`)

#### Pydantic Schemas (`src/osint_core/schemas/audit.py`)

| Class | Purpose |
|-------|---------|
| `AuditLogResponse` | Read serialization |
| `AuditLogList` | Paginated collection of `AuditLogResponse` |

---

### Brief

**File:** `src/osint_core/models/brief.py`
**Table:** `osint.briefs`

An AI-generated intelligence brief summarizing events, entities, and indicators.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `title` | Text | No | Brief title |
| `content_md` | Text | No | Markdown body |
| `content_pdf_uri` | Text | Yes | Object storage URI for PDF rendition |
| `target_query` | Text | Yes | Query that prompted the brief |
| `event_ids` | ARRAY(UUID) | No | Events cited in the brief |
| `entity_ids` | ARRAY(UUID) | No | Entities cited |
| `indicator_ids` | ARRAY(UUID) | No | Indicators cited |
| `generated_by` | Text | No | Default `vllm`; generation backend |
| `model_id` | Text | Yes | Specific model identifier |
| `plan_version_id` | UUID (FK) | Yes | References `osint.plan_versions.id` |
| `requested_by` | Text | Yes | User who requested the brief |

#### Relationships

- `plan_version` -> `PlanVersion` (many-to-one, selectin)

#### Pydantic Schemas (`src/osint_core/schemas/brief.py`)

| Class | Purpose |
|-------|---------|
| `BriefResponse` | Read serialization |
| `BriefList` | Paginated collection of `BriefResponse` |
| `BriefCreateRequest` | Request a new brief by providing a natural-language query |

---

### Job

**File:** `src/osint_core/models/job.py`
**Table:** `osint.jobs`

A tracked background job (Celery task or Kubernetes Job).

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `job_type` | Text | No | Kind of job |
| `status` | Text | No | Default `queued`; constrained to `queued`, `running`, `succeeded`, `failed`, `partial_success`, `dead_letter` |
| `celery_task_id` | Text | Yes | Celery task identifier |
| `k8s_job_name` | Text | Yes | Kubernetes job name |
| `input_params` | JSONB | No | Job input parameters |
| `output` | JSONB | No | Job output / result |
| `error` | Text | Yes | Error message on failure |
| `retry_count` | Integer | No | Default `0` |
| `next_retry_at` | TIMESTAMP(tz) | Yes | Scheduled retry time |
| `idempotency_key` | Text | Yes | Unique per-job deduplication key |
| `plan_version_id` | UUID (FK) | Yes | References `osint.plan_versions.id` |
| `started_at` | TIMESTAMP(tz) | Yes | When execution started |
| `completed_at` | TIMESTAMP(tz) | Yes | When execution finished |

#### Relationships

- `plan_version` -> `PlanVersion` (many-to-one, selectin)

#### Indexes

- `ix_jobs_idempotency_key` (unique, partial: where `idempotency_key IS NOT NULL`)

#### Pydantic Schemas (`src/osint_core/schemas/job.py`)

| Class | Purpose |
|-------|---------|
| `JobResponse` | Read serialization; aliases `job_type` to `kind`, `input_params` to `input`, `output` to `result`, `created_at` to `submitted_at` |
| `JobList` | Paginated collection of `JobResponse` |
| `JobCreateRequest` | Submit a job; `kind` constrained to `ingest`, `rescore`, `brief_generate` |

---

### Lead

**File:** `src/osint_core/models/lead.py`
**Table:** `osint.leads`

A prospecting lead surfaced from OSINT events and qualified through a pipeline.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `lead_type` | Text | No | Constrained to `incident`, `policy` |
| `status` | Text | No | Default `new`; constrained to `new`, `reviewing`, `qualified`, `contacted`, `retained`, `declined`, `stale` |
| `title` | Text | No | Lead headline |
| `summary` | Text | Yes | Descriptive summary |
| `constitutional_basis` | ARRAY(Text) | No | Constitutional provisions involved |
| `jurisdiction` | Text | Yes | Relevant jurisdiction |
| `institution` | Text | Yes | Related institution |
| `severity` | Text | Yes | Constrained to `info`, `low`, `medium`, `high`, `critical` |
| `confidence` | Float | Yes | Constrained 0.0 - 1.0 |
| `dedupe_fingerprint` | Text | No | Unique deduplication hash |
| `plan_id` | Text | Yes | Associated plan identifier |
| `event_ids` | ARRAY(UUID) | No | Source event IDs |
| `entity_ids` | ARRAY(UUID) | No | Related entity IDs |
| `citations` | JSONB | Yes | Structured citation data |
| `report_id` | UUID | Yes | Associated report ID |
| `first_surfaced_at` | TIMESTAMP(tz) | No | Server-default `now()` |
| `last_updated_at` | TIMESTAMP(tz) | No | Server-default `now()` |
| `reported_at` | TIMESTAMP(tz) | Yes | When included in a report |

#### Indexes

- `ix_leads_dedupe_fingerprint` (unique)
- `ix_leads_status`
- `ix_leads_jurisdiction`
- `ix_leads_reported_at`
- `ix_leads_plan_id`

#### Pydantic Schemas (`src/osint_core/schemas/lead.py`)

| Class | Purpose |
|-------|---------|
| `LeadResponse` | Read serialization with typed enums |
| `LeadListResponse` | Paginated collection of `LeadResponse` |
| `LeadUpdateRequest` | Update lead lifecycle status |
| `LeadTypeEnum` | `incident`, `policy` |
| `LeadStatusEnum` | `new`, `reviewing`, `qualified`, `contacted`, `retained`, `declined`, `stale` |

---

### PlanVersion

**File:** `src/osint_core/models/plan.py`
**Table:** `osint.plan_versions`

A versioned snapshot of an intelligence collection plan. Plans are identified by `plan_id` and versioned with an incrementing integer.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `plan_id` | Text | No | Logical plan identifier |
| `version` | Integer | No | Monotonically increasing version number |
| `content_hash` | Text | No | SHA hash of plan content |
| `content` | JSONB | No | Full plan definition |
| `retention_class` | Text | No | Constrained to `ephemeral`, `standard`, `evidentiary` |
| `git_commit_sha` | Text | Yes | Commit SHA that introduced this version |
| `activated_at` | TIMESTAMP(tz) | Yes | When this version was activated |
| `activated_by` | Text | Yes | Who activated it |
| `is_active` | Boolean | No | Default `false`; whether this is the live version |
| `validation_result` | JSONB | Yes | Schema validation output |

#### Constraints

- Unique on (`plan_id`, `version`)
- Check: `retention_class` in `ephemeral`, `standard`, `evidentiary`

#### Pydantic Schemas (`src/osint_core/schemas/plan.py`)

| Class | Purpose |
|-------|---------|
| `PlanVersionResponse` | Read serialization |
| `PlanVersionList` | Paginated collection |
| `PlanCreateRequest` | Create a new version from YAML; optionally activate |
| `PlanActivationRequest` | Activate a specific version or roll back |
| `PlanValidationResult` | Validation output (errors, warnings, diff summary) |

---

### Report

**File:** `src/osint_core/models/report.py`
**Table:** `osint.reports`

A generated prospecting report artifact aggregating qualified leads.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `artifact_uri` | Text | No | Object storage URI for the report file |
| `generated_at` | TIMESTAMP(tz) | No | Server-default `now()` |
| `lead_count` | Integer | No | Number of leads in the report |
| `plan_id` | Text | Yes | Associated plan identifier |

#### Indexes

- `ix_reports_plan_id`
- `ix_reports_generated_at`

#### Pydantic Schemas

No dedicated schema file. Reports are referenced by `Lead.report_id`.

---

### UserPreference

**File:** `src/osint_core/models/user_preference.py`
**Table:** `osint.user_preferences`

Per-user settings and saved searches, keyed by Keycloak `sub` claim.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `user_sub` | Text | No | Unique Keycloak subject identifier |
| `notification_prefs` | JSONB | No | Notification settings |
| `saved_searches` | JSONB | No | Array of saved search objects |
| `timezone` | Text | No | Default `UTC` |
| `updated_at` | TIMESTAMP(tz) | No | Server-default `now()`; auto-updated on change |

#### Indexes

- `ix_user_preferences_user_sub` (unique)

#### Pydantic Schemas (`src/osint_core/schemas/preference.py`)

| Class | Purpose |
|-------|---------|
| `PreferenceResponse` | Read serialization |
| `PreferenceUpdateRequest` | Update notification prefs and/or timezone |
| `SavedSearchRequest` | Create a saved search (name, query, filters, alert toggle) |
| `SavedSearchResponse` | Read serialization for a saved search |

---

### Watch

**File:** `src/osint_core/models/watch.py`
**Table:** `osint.watches`

A regional or topic-based intelligence watch that matches incoming events.

#### Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | PK |
| `created_at` | TIMESTAMP | No | Server-default `now()` |
| `name` | Text | No | Unique watch name |
| `watch_type` | Text | No | Constrained to `persistent`, `dynamic` |
| `status` | Text | No | Default `active`; constrained to `active`, `paused`, `expired`, `promoted` |
| `region` | Text | Yes | Geographic region |
| `country_codes` | ARRAY(Text) | Yes | ISO country codes |
| `bounding_box` | JSONB | Yes | Geographic bounding box (`north`, `south`, `east`, `west`) |
| `keywords` | ARRAY(Text) | Yes | Keyword filters |
| `source_filter` | ARRAY(Text) | Yes | Source category filters |
| `severity_threshold` | Text | No | Default `medium`; constrained to severity values |
| `plan_id` | Text | Yes | Associated plan identifier |
| `ttl_hours` | Integer | Yes | Time-to-live for dynamic watches |
| `expires_at` | TIMESTAMP(tz) | Yes | Computed expiration time |
| `promoted_at` | TIMESTAMP(tz) | Yes | When promoted from dynamic to persistent |
| `created_by` | Text | No | Default `manual` |

#### Relationships

- `events` -> `Event` (many-to-many via `watch_events`)

#### Association Table

| Table | Columns | Description |
|-------|---------|-------------|
| `watch_events` | `watch_id`, `event_id` | Links watches to matched events (CASCADE delete) |

#### Indexes

- `ix_watches_status`
- `ix_watches_plan_id`

#### Pydantic Schemas (`src/osint_core/schemas/watch.py`)

| Class | Purpose |
|-------|---------|
| `WatchResponse` | Read serialization |
| `WatchList` | Paginated collection |
| `WatchCreateRequest` | Create a new watch with region, keywords, bounding box, etc. |
| `WatchUpdateRequest` | Partial update of watch configuration |
| `WatchTypeEnum` | `persistent`, `dynamic` |
| `WatchStatusEnum` | `active`, `paused`, `expired`, `promoted` |
| `BoundingBox` | Nested model for geographic bounds |

---

## Entity Relationship Summary

The data model is centered on **Event** as the primary intelligence record. Most other models connect to events directly or indirectly:

- **Event** links to **Entity**, **Indicator**, and **Artifact** through many-to-many association tables (`event_entities`, `event_indicators`, `event_artifacts`).
- **Event** has an optional self-referencing foreign key (`canonical_event_id`) for near-duplicate grouping.
- **PlanVersion** is the configuration backbone. **Event**, **Alert**, **Artifact**, **Brief**, and **Job** each hold an optional `plan_version_id` foreign key pointing to the plan version that governed their creation.
- **Alert** stores arrays of `event_ids`, `indicator_ids`, and `entity_ids` as denormalized UUID arrays rather than foreign-key joins, optimizing read performance for alert display.
- **Brief** similarly stores `event_ids`, `entity_ids`, and `indicator_ids` as UUID arrays referencing the intelligence items it summarizes.
- **Lead** references events and entities via UUID arrays (`event_ids`, `entity_ids`) and optionally links to a **Report** through `report_id`.
- **Report** aggregates leads into a generated document and tracks the count via `lead_count`.
- **Watch** links to matched **Event** records through the `watch_events` association table and optionally references a plan by `plan_id` (text, not FK).
- **Job** tracks asynchronous work (ingestion, rescoring, brief generation) and is tied to a plan version.
- **AuditLog** is a standalone, append-only table with no foreign keys — it records actions against any resource by type and ID.
- **UserPreference** is a standalone table keyed by Keycloak `user_sub` with no foreign keys to other models.
