# API Reference

All endpoints are served under the `/api/v1` prefix (configurable via the `OSINT_API_PREFIX` environment variable). The OpenAPI spec is available at `/api/v1/openapi.json` and the interactive docs at `/api/v1/docs`.

Source: `src/osint_core/main.py`

---

## Authentication

Authentication uses **Keycloak OIDC** with RS256-signed JWT bearer tokens. Include an `Authorization: Bearer <token>` header on every request that requires auth.

| Setting | Default | Description |
|---|---|---|
| `AUTH_DISABLED` | `True` | When true, all authenticated endpoints return a default admin user without checking tokens. Intended for dev/test environments. |
| `KEYCLOAK_URL` | -- | Base URL of the Keycloak server. |
| `KEYCLOAK_REALM` | -- | Keycloak realm name. |
| `KEYCLOAK_CLIENT_ID` | -- | Expected `aud` claim in the JWT. |

The dependency `get_current_user` (defined in `src/osint_core/api/deps.py`) extracts a `UserInfo` object with fields `sub`, `username`, and `roles`. Certain endpoints use `require_role("admin")` to restrict access by realm role.

JWKS keys are fetched from `{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs` and cached for 5 minutes.

Source: `src/osint_core/api/middleware/auth.py`

---

## Rate Limiting

A Redis-backed fixed-window rate limiter is applied as middleware to all requests except exempt health/metrics paths.

| Setting | Default | Description |
|---|---|---|
| `RATE_LIMIT_PER_IP` | `100` | Max requests per IP per 60-second window. |
| `RATE_LIMIT_PER_USER` | `300` | Max requests per authenticated user per 60-second window. |
| `RATE_LIMIT_TRUST_PROXY` | `True` | When true, reads client IP from the `X-Forwarded-For` header. |

**Behavior:**
- When a limit is exceeded the API returns `429 Too Many Requests` with a `Retry-After` header.
- The `X-RateLimit-Remaining` header is included on successful responses.
- If Redis is unavailable, requests are allowed through (fail-open).

**Exempt paths:** `/healthz`, `/readyz`, `/metrics`, `/api/v1/system/health`, `/api/v1/system/readiness`

Source: `src/osint_core/api/middleware/rate_limit.py`

---

## Error Responses

All errors conform to an RFC 7807-style `ProblemDetails` envelope:

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "code": "not_found",
  "detail": "Entity not found",
  "instance": "/api/v1/entities/abc",
  "request_id": "...",
  "errors": []
}
```

The `errors` array contains `FieldError` objects for validation failures:

```json
{
  "field": "limit",
  "message": "ensure this value is greater than or equal to 1",
  "code": "value_error"
}
```

Common error codes: `bad_request`, `auth_required`, `forbidden`, `not_found`, `conflict`, `validation_failed`, `dependency_unavailable`.

Source: `src/osint_core/api/errors.py`, `src/osint_core/schemas/common.py`

---

## Endpoints

All paginated list endpoints accept `limit` (default 50, max 200) and `offset` (default 0) query parameters and return a `page` object with `offset`, `limit`, `total`, and `has_more`.

### Health

Source: `src/osint_core/api/routes/health.py`

These endpoints have no auth requirement and are exempt from rate limiting.

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/healthz` | Liveness probe (legacy) | No |
| GET | `/api/v1/system/health` | Liveness probe | No |
| GET | `/readyz` | Readiness probe -- checks Postgres, Redis, Qdrant (legacy) | No |
| GET | `/api/v1/system/readiness` | Readiness probe -- checks Postgres, Redis, Qdrant | No |
| GET | `/metrics` | Prometheus metrics | No |

---

### Plans

Source: `src/osint_core/api/routes/plan.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/plans:validate` | Validate a plan YAML payload without persisting | Yes |
| GET | `/api/v1/plans` | List active plan versions | Yes |
| POST | `/api/v1/plans` | Create a new plan version from YAML | Yes |
| GET | `/api/v1/plans/{plan_id}/active-version` | Get the active plan version | Yes |
| PATCH | `/api/v1/plans/{plan_id}/active-version` | Activate a specific version or roll back | Yes |
| GET | `/api/v1/plans/{plan_id}/versions` | List all stored versions for a plan | Yes |
| GET | `/api/v1/plans/{plan_id}/versions/{version_id}` | Get a specific plan version | Yes |
| POST | `/api/v1/plans:sync-from-disk` | Reload plan files from disk and activate changed versions | Yes |

#### POST `/api/v1/plans:validate`

Validate a plan YAML payload without persisting it. The request body is raw YAML (read from `request.body()`).

- **Response:** `PlanValidationResult` -- `is_valid`, `errors`, `warnings`

#### POST `/api/v1/plans`

Persist a new plan version from YAML content.

- **Request body:** `PlanCreateRequest` -- `yaml` (string), `git_commit_sha` (optional), `activate` (bool)
- **Response:** `PlanVersionResponse` (201 Created)
- **Errors:** 409 on duplicate content hash conflict

#### GET `/api/v1/plans/{plan_id}/active-version`

- **Path params:** `plan_id` (string)
- **Response:** `PlanVersionResponse`
- **Errors:** 404 if no active version

#### PATCH `/api/v1/plans/{plan_id}/active-version`

- **Path params:** `plan_id` (string)
- **Request body:** `PlanActivationRequest` -- `version_id` (UUID, optional), `rollback` (bool)
- **Response:** `PlanVersionResponse`
- **Errors:** 404 if no matching version, 409 if version does not belong to the target plan

#### GET `/api/v1/plans/{plan_id}/versions`

- **Path params:** `plan_id` (string)
- **Query params:** `limit`, `offset`
- **Response:** `PlanVersionList`

#### GET `/api/v1/plans/{plan_id}/versions/{version_id}`

- **Path params:** `plan_id` (string), `version_id` (UUID)
- **Response:** `PlanVersionResponse`
- **Errors:** 404 if version not found

#### POST `/api/v1/plans:sync-from-disk`

Reload plan files from the configured `PLAN_DIR` directory, create new versions for any changed files, and activate them.

- **Response:** `PlanVersionList` of newly synced versions

---

### Events

Source: `src/osint_core/api/routes/events.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/events` | List events with optional filters | Yes |
| GET | `/api/v1/events/{event_id}` | Get a single event by ID | Yes |

#### GET `/api/v1/events`

- **Query params:**
  - `limit`, `offset` -- pagination
  - `source_id` (string) -- filter by source
  - `severity` (string) -- filter by severity
  - `date_from`, `date_to` (datetime) -- filter by ingestion date range
  - `attack_technique` (string) -- filter by MITRE ATT&CK technique ID (e.g. `T1566`), matches via JSONB containment
  - `sort` (string) -- sort field, prefix with `-` for descending. Supported: `ingested_at`, `occurred_at`, `score`
- **Response:** `EventList`

#### GET `/api/v1/events/{event_id}`

- **Path params:** `event_id` (UUID)
- **Response:** `EventResponse`
- **Errors:** 404 if not found

---

### Indicators

Source: `src/osint_core/api/routes/indicators.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/indicators` | List indicators with optional type filter | Yes |
| GET | `/api/v1/indicators/{indicator_id}` | Get a single indicator by ID | Yes |

#### GET `/api/v1/indicators`

- **Query params:** `limit`, `offset`, `indicator_type` (string)
- **Response:** `IndicatorList`

#### GET `/api/v1/indicators/{indicator_id}`

- **Path params:** `indicator_id` (UUID)
- **Response:** `IndicatorResponse`
- **Errors:** 404 if not found

---

### Entities

Source: `src/osint_core/api/routes/entities.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/entities` | List entities with optional type filter | Yes |
| GET | `/api/v1/entities/{entity_id}` | Get a single entity by ID | Yes |

#### GET `/api/v1/entities`

- **Query params:** `limit`, `offset`, `entity_type` (string)
- **Response:** `EntityList`

#### GET `/api/v1/entities/{entity_id}`

- **Path params:** `entity_id` (UUID)
- **Response:** `EntityResponse`
- **Errors:** 404 if not found

---

### Alerts

Source: `src/osint_core/api/routes/alerts.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/alerts` | List alerts with optional status and severity filters | Yes |
| GET | `/api/v1/alerts/{alert_id}` | Get a single alert by ID | Yes |
| PATCH | `/api/v1/alerts/{alert_id}` | Update alert lifecycle state | Yes |

#### GET `/api/v1/alerts`

- **Query params:** `limit`, `offset`, `status` (string), `severity` (string)
- **Response:** `AlertList`

#### GET `/api/v1/alerts/{alert_id}`

- **Path params:** `alert_id` (UUID)
- **Response:** `AlertResponse`
- **Errors:** 404 if not found

#### PATCH `/api/v1/alerts/{alert_id}`

- **Path params:** `alert_id` (UUID)
- **Request body:** `AlertUpdateRequest` -- `status` (string)
- **Response:** `AlertResponse`
- **Errors:** 404 if not found, 409 if already in the requested status or if attempting to resolve an open alert without acknowledging first

---

### Briefs

Source: `src/osint_core/api/routes/briefs.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/briefs` | List intelligence briefs | Yes |
| GET | `/api/v1/briefs/{brief_id}` | Get a single brief by ID | Yes |
| GET | `/api/v1/briefs/{brief_id}/pdf` | Export a brief as PDF | Yes |
| POST | `/api/v1/briefs` | Generate and persist a new intelligence brief | Yes |

#### GET `/api/v1/briefs`

- **Query params:** `limit`, `offset`
- **Response:** `BriefList`

#### GET `/api/v1/briefs/{brief_id}`

- **Path params:** `brief_id` (UUID)
- **Response:** `BriefResponse`
- **Errors:** 404 if not found

#### GET `/api/v1/briefs/{brief_id}/pdf`

Export a brief as a PDF document. The PDF is rendered from the brief's markdown content and uploaded to MinIO.

- **Path params:** `brief_id` (UUID)
- **Response:** `application/pdf` binary
- **Errors:** 404 if not found, 503 if PDF rendering fails

#### POST `/api/v1/briefs`

Generate a new intelligence brief using the configured LLM. The brief is built from events, indicators, and entities matching the query.

- **Request body:** `BriefCreateRequest` -- `query` (string)
- **Response:** `BriefResponse` (201 Created)
- **Errors:** 503 if LLM generation fails

---

### Search

Source: `src/osint_core/api/routes/search.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/search/events` | Full-text search over events (Postgres tsvector) | Yes |
| GET | `/api/v1/search/events:semantic` | Semantic similarity search via Qdrant | Yes |

#### GET `/api/v1/search/events`

- **Query params:**
  - `q` (string, required) -- search query
  - `limit`, `offset`
- **Response:** `EventSearchList` (includes `retrieval_mode: "lexical"`)

#### GET `/api/v1/search/events:semantic`

Dispatches embedding to a Celery worker and queries Qdrant for similar events.

- **Query params:**
  - `q` (string, required) -- natural language query
  - `limit` (default 20, max 100)
  - `score_threshold` (float, default 0.5, range 0.0-1.0)
- **Response:** `EventSearchList` (includes `retrieval_mode: "semantic"`)
- **Errors:** 503 if semantic search is unavailable

---

### Jobs

Source: `src/osint_core/api/routes/jobs.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/jobs` | Create and dispatch an asynchronous platform job | Yes |
| GET | `/api/v1/jobs` | List jobs with optional filters | Yes |
| GET | `/api/v1/jobs/{job_id}` | Get a single job by ID | Yes |

#### POST `/api/v1/jobs`

Create and dispatch a new asynchronous job. Supported job kinds: `ingest`, `rescore`, `brief_generate`.

- **Request body:** `JobCreateRequest` -- `kind` (`JobKindEnum`), `input` (dict), `idempotency_key` (string, optional)
- **Response:** `JobResponse` (202 Accepted). Returns 200 if the idempotency key matches an existing job.
- **Required inputs by kind:**
  - `ingest`: `source_id`, `plan_id`
  - `rescore`: `plan_id` (optional)
  - `brief_generate`: `query`
- **Errors:** 409 on idempotency conflict, 422 on missing inputs or unsupported kind, 503 if brief generation fails

#### GET `/api/v1/jobs`

- **Query params:** `limit`, `offset`, `kind` (`JobKindEnum`), `status` (`JobStatusEnum`)
- **Response:** `JobList`

#### GET `/api/v1/jobs/{job_id}`

- **Path params:** `job_id` (UUID)
- **Response:** `JobResponse`
- **Errors:** 404 if not found

---

### Audit

Source: `src/osint_core/api/routes/audit.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/audit` | List audit log entries | Yes |

#### GET `/api/v1/audit`

- **Query params:** `limit`, `offset`, `action` (string, optional)
- **Response:** `AuditLogList`

---

### Watches

Source: `src/osint_core/api/routes/watches.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/watches` | Create a new watch | Yes |
| GET | `/api/v1/watches` | List watches with optional status filter | Yes |
| GET | `/api/v1/watches/{watch_id}` | Get a single watch by ID | Yes |
| PATCH | `/api/v1/watches/{watch_id}` | Update a watch | Yes |
| DELETE | `/api/v1/watches/{watch_id}` | Delete a watch | Yes |

#### POST `/api/v1/watches`

- **Request body:** `WatchCreateRequest` -- `name`, `region`, `country_codes`, `bounding_box`, `keywords`, `source_filter`, `severity_threshold`, `plan_id`, `ttl_hours`
- **Response:** `WatchResponse` (201 Created)
- **Errors:** 409 if a watch with the same name already exists

#### GET `/api/v1/watches`

- **Query params:** `limit`, `offset`, `status` (`WatchStatusEnum`)
- **Response:** `WatchList`

#### GET `/api/v1/watches/{watch_id}`

- **Path params:** `watch_id` (UUID)
- **Response:** `WatchResponse`
- **Errors:** 404 if not found

#### PATCH `/api/v1/watches/{watch_id}`

- **Path params:** `watch_id` (UUID)
- **Request body:** `WatchUpdateRequest` -- all fields optional (partial update)
- **Response:** `WatchResponse`
- **Errors:** 404 if not found, 409 if attempting an invalid state transition

#### DELETE `/api/v1/watches/{watch_id}`

- **Path params:** `watch_id` (UUID)
- **Response:** 204 No Content
- **Errors:** 404 if not found

---

### Leads

Source: `src/osint_core/api/routes/leads.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/leads` | List leads with optional filters | Yes |
| GET | `/api/v1/leads/{lead_id}` | Get a single lead with full citations | Yes |
| PATCH | `/api/v1/leads/{lead_id}` | Update a lead's status | Yes |

#### GET `/api/v1/leads`

- **Query params:** `limit`, `offset`, `status` (string), `jurisdiction` (string), `lead_type` (string), `plan_id` (string), `date_from`, `date_to` (datetime)
- **Response:** `LeadListResponse`

#### GET `/api/v1/leads/{lead_id}`

- **Path params:** `lead_id` (UUID)
- **Response:** `LeadResponse`
- **Errors:** 404 if not found

#### PATCH `/api/v1/leads/{lead_id}`

Update a lead's status with transition validation. Valid transitions:

| From | Allowed Next |
|---|---|
| `new` | `reviewing`, `declined`, `stale` |
| `reviewing` | `qualified`, `declined`, `stale` |
| `qualified` | `contacted`, `declined`, `stale` |
| `contacted` | `retained`, `declined`, `stale` |
| `retained` | (terminal) |
| `declined` | (terminal) |
| `stale` | `reviewing` |

- **Path params:** `lead_id` (UUID)
- **Request body:** `LeadUpdateRequest` -- `status` (string)
- **Response:** `LeadResponse`
- **Errors:** 404 if not found, 422 if the status transition is invalid

---

### Preferences

Source: `src/osint_core/api/routes/preferences.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/preferences` | Get the authenticated user's preferences | Yes |
| PUT | `/api/v1/preferences` | Update the authenticated user's preferences | Yes |

#### GET `/api/v1/preferences`

- **Response:** `PreferenceResponse`

#### PUT `/api/v1/preferences`

- **Request body:** `PreferenceUpdateRequest` -- `notification_prefs` (object, optional), `timezone` (string, optional)
- **Response:** `PreferenceResponse`

---

### Saved Searches

Source: `src/osint_core/api/routes/preferences.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/saved-searches` | Create a saved search | Yes |
| GET | `/api/v1/saved-searches` | List saved searches for the authenticated user | Yes |
| DELETE | `/api/v1/saved-searches/{search_id}` | Delete a saved search | Yes |

#### POST `/api/v1/saved-searches`

- **Request body:** `SavedSearchRequest` -- `name`, `query`, `filters`, `alert_enabled`
- **Response:** `SavedSearchResponse` (201 Created)

#### GET `/api/v1/saved-searches`

- **Response:** `list[SavedSearchResponse]`

#### DELETE `/api/v1/saved-searches/{search_id}`

- **Path params:** `search_id` (string)
- **Response:** 204 No Content
- **Errors:** 404 if not found

---

### Ingest

Source: `src/osint_core/api/routes/ingest.py`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/ingest/source/{source_id}/run` | Dispatch a Celery ingest task for a source | Yes |

#### POST `/api/v1/ingest/source/{source_id}/run`

- **Path params:** `source_id` (string)
- **Query params:** `plan_id` (string, required)
- **Response:** `{ task_id, source_id, plan_id, status: "dispatched" }`

---

## Endpoint Count Summary

| Router | Endpoints |
|---|---|
| Health | 5 |
| Plans | 8 |
| Events | 2 |
| Indicators | 2 |
| Entities | 2 |
| Alerts | 3 |
| Briefs | 4 |
| Search | 2 |
| Jobs | 3 |
| Audit | 1 |
| Watches | 5 |
| Leads | 3 |
| Preferences | 2 |
| Saved Searches | 3 |
| Ingest | 1 |
| **Total** | **46** |
