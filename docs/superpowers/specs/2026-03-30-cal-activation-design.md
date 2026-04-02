# CAL Prospecting Activation & Test Run — Design Spec

**Date:** 2026-03-30
**Status:** Approved
**Scope:** First-time activation of the `cal-prospecting` plan on the deployed instance (osint.corbello.io), full-cycle ingestion test across all 14 sources, report generation with PDF delivered to operator email for review.

---

## Context

Epic #141 (CAL Constitutional Prospecting) is complete — 42 issues across 11 phases, all merged. The `cal-prospecting.yaml` plan is in the repo and deployed via CI, but has never been synced/activated on the production instance. This spec covers the operational steps to activate it, run a full test cycle, and validate outputs before enabling the cron schedule for live operation.

---

## Prerequisites

### Environment Variables

The following env var mappings are **missing** from the K8s deployments (`osint-core`, `osint-worker`, `osint-beat`) and must be added in `cortech-infra`:

| App Env Var | K8s Secret Key | Source | Status |
|-------------|---------------|--------|--------|
| `OSINT_XAI_API_KEY` | `osint-secrets/XAI_API_KEY` | Infisical `osint` folder | Secret exists, mapping missing |
| `OSINT_COURTLISTENER_API_KEY` | `osint-secrets/COURTLISTENER_API_KEY` | Infisical `osint` folder | Secret exists, mapping missing |
| `OSINT_RESEND_API_KEY` | `osint-secrets/RESEND_API_KEY` | Infisical `RESEND_API_KEY_PERSONAL` | Must add to K8s secret + mapping |
| `CAL_REPORT_RECIPIENT_1` | `osint-secrets/CAL_REPORT_RECIPIENT_1` | Operator email (test) | Must add to K8s secret + mapping |
| `CAL_REPORT_RECIPIENT_2` | `osint-secrets/CAL_REPORT_RECIPIENT_2` | Operator email (test) | Must add to K8s secret + mapping |

**Infisical references:**
- `XAI_API_KEY` and `COURTLISTENER_API_KEY` are in the `osint` folder
- `RESEND_API_KEY_PERSONAL` is the Infisical key name for the Resend API key
- CourtListener project ID: `c00e26a9-9389-4cc8-9b74-75f936dfeb81`

### Deployment Changes

All three K8s deployments need the env var additions patched via kustomize in `cortech-infra`, followed by a rolling restart:

```bash
kubectl -n osint rollout restart deployment/osint-core
kubectl -n osint rollout restart deployment/osint-worker
kubectl -n osint rollout restart deployment/osint-beat
```

---

## Step 1: Environment Setup

1. Add `RESEND_API_KEY`, `CAL_REPORT_RECIPIENT_1`, and `CAL_REPORT_RECIPIENT_2` to K8s secret `osint-secrets`
2. Patch all three deployments in `cortech-infra` to add the five env var mappings listed above
3. Trigger ArgoCD sync or rolling restart
4. Verify pods are healthy after restart

---

## Step 2: Plan Activation

1. Sync plans from disk:
   ```
   POST /api/v1/plans:sync-from-disk
   ```
2. Verify activation:
   ```
   GET /api/v1/plans/cal-prospecting/active-version
   ```
   Expect: 200 with `plan_id: cal-prospecting`, `activated_at` set

---

## Step 3: Full-Cycle Ingestion

Trigger all 14 sources manually via the ingest API, in three batches by connector type. This isolates failures by type while still exercising the full pipeline.

### Batch 1: RSS (4 sources)

| Source ID | Feed |
|-----------|------|
| `rss_fire` | FIRE (thefire.org) |
| `rss_higher_ed_dive` | Higher Ed Dive |
| `rss_volokh` | Reason / Volokh Conspiracy |
| `rss_courthouse_news` | Courthouse News Service |

```
POST /api/v1/ingest/source/{source_id}/run?plan_id=cal-prospecting
```

Monitor via `GET /api/v1/jobs?kind=ingest` — wait for all 4 to succeed before proceeding.

### Batch 2: xAI x_search (4 sources)

| Source ID | Jurisdiction |
|-----------|-------------|
| `x_cal_california` | California |
| `x_cal_texas` | Texas |
| `x_cal_minnesota` | Minnesota |
| `x_cal_dc` | DC / Federal |

These hit the xAI API with Grok — costs API credits. Each source runs up to 4 search queries with `max_results: 50`.

### Batch 3: University Policy (6 sources)

| Source ID | Institution |
|-----------|------------|
| `univ_uc` | University of California System |
| `univ_csu` | California State University System |
| `univ_ut` | University of Texas System |
| `univ_tamu` | Texas A&M University System |
| `univ_umn` | University of Minnesota |
| `univ_udc` | University of the District of Columbia |

These scrape live university policy portals. First run will baseline all policies (no prior content hashes to diff against), so expect a larger-than-usual number of RawItems.

### Post-Ingestion Verification

After all 14 sources complete:

1. Check events exist: `GET /api/v1/events?plan_id=cal-prospecting&limit=10`
2. Check leads were created: `GET /api/v1/leads?plan_id=cal-prospecting`
3. Verify lead fields: `constitutional_basis`, `jurisdiction`, `severity`, `confidence`, `dedupe_fingerprint`
4. Check for any failed jobs: `GET /api/v1/jobs?kind=ingest&status=failed`

---

## Step 4: Report Generation

After the enrichment chain completes (NLP → score → vectorize → entity extraction → lead matching):

1. Trigger the prospecting report generation task manually via Celery:
   ```
   celery -A osint_core.workers.celery_app call osint.generate_prospecting_report
   ```
   Or from a worker pod:
   ```bash
   kubectl -n osint exec deploy/osint-worker -- celery -A osint_core.workers.celery_app call osint.generate_prospecting_report
   ```
2. The report generator will:
   - Select leads where `status = 'new'`
   - Generate a consolidated PDF via WeasyPrint
   - Archive the PDF to MinIO (`retention_class: evidentiary`)
   - Verify legal citations against CourtListener
   - Send via Resend to the operator's test email
3. Mark leads as `reported_at = now`, `status → 'reviewing'`

### Output Review Checklist

- [ ] PDF received via email
- [ ] Cover page has correct branding and date
- [ ] Executive summary shows lead counts by type and jurisdiction
- [ ] Incident leads have: who/what/where, constitutional analysis, citations
- [ ] Policy leads have: policy excerpts, facial challenge analysis, citations
- [ ] Citations appendix has source material + legal citations with verification status
- [ ] No hallucinated legal citations (all should be from source material or CourtListener-verified)
- [ ] Lead records in DB have `report_id` populated

---

## Step 5: Post-Test Decision

After reviewing the test report:

**If satisfactory:**
1. Swap `CAL_REPORT_RECIPIENT_1`/`2` to actual CAL recipient email addresses
2. The existing Celery Beat static schedule handles ongoing operation:
   - Collection: 07:00 and 14:00 CT
   - Report generation: 08:00 and 15:00 CT
3. PlanScheduler also picks up per-source `schedule_cron` entries from the plan for dynamic scheduling

**If tuning needed:**
- Adjust search queries, confidence threshold (`lead_confidence_threshold: 0.3`), or scoring weights in `cal-prospecting.yaml`
- Re-sync plans and run another test cycle
- No code changes needed — all tuning is in plan YAML

---

## Risk Considerations

- **University policy scraper first run:** Will baseline all policies, producing many RawItems. Subsequent runs only detect changes via content hash diff.
- **xAI API costs:** 4 jurisdictions × 4 queries × 50 max results = up to 800 items. Single test run cost is minimal.
- **CourtListener rate limits:** Verification is rate-limited in the client. Large numbers of leads with legal citations may slow report generation.
- **Email delivery:** Test emails go to operator only. No risk of premature CAL notification.
