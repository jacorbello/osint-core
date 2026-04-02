# CAL Prospecting Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the `cal-prospecting` plan on production, run a full 14-source ingestion cycle, generate a test report, and review outputs.

**Architecture:** Operational activation — no code changes. Add missing secrets to Infisical, patch three K8s deployment manifests in cortech-infra to map new env vars, sync the plan, trigger ingestion, and generate a report.

**Tech Stack:** Kubernetes, Infisical operator, Celery, FastAPI, kustomize, ArgoCD

---

### Task 1: Add Missing Secrets to Infisical

The Infisical operator syncs secrets from project `c00e26a9-9389-4cc8-9b74-75f936dfeb81`, env `prod`, path `/osint` into K8s secret `osint-secrets` every 60s.

**Current state of `osint-secrets`:**
- `XAI_API_KEY` — present
- `COURTLISTENER_API_KEY` — present
- `RESEND_API_KEY` — missing
- `CAL_REPORT_RECIPIENT_1` — missing
- `CAL_REPORT_RECIPIENT_2` — missing

**Files:**
- Modify: Infisical project `c00e26a9-9389-4cc8-9b74-75f936dfeb81` → `prod` → `/osint`

- [ ] **Step 1: Add RESEND_API_KEY to Infisical /osint path**

The Resend key exists in Infisical as `RESEND_API_KEY_PERSONAL` (different path/name). Copy its value into the `/osint` folder as `RESEND_API_KEY`:

```bash
# Get the value from the existing location
infisical secrets get RESEND_API_KEY_PERSONAL --env=prod

# Set it in the /osint path
infisical secrets set RESEND_API_KEY="<value>" --env=prod --path=/osint
```

Or use the Infisical web UI to create `RESEND_API_KEY` in `prod` → `/osint`.

- [ ] **Step 2: Add CAL_REPORT_RECIPIENT_1 to Infisical /osint path**

Set to the operator's personal email for test runs:

```bash
infisical secrets set CAL_REPORT_RECIPIENT_1="<your-email>" --env=prod --path=/osint
```

- [ ] **Step 3: Add CAL_REPORT_RECIPIENT_2 to Infisical /osint path**

Set to the same email (or a second test email):

```bash
infisical secrets set CAL_REPORT_RECIPIENT_2="<your-email>" --env=prod --path=/osint
```

- [ ] **Step 4: Verify secrets synced to K8s (wait ~60s for Infisical operator)**

```bash
kubectl -n osint get secret osint-secrets -o jsonpath='{.data}' | python3 -c "
import sys, json, base64
data = json.loads(sys.stdin.read())
for k in ['RESEND_API_KEY', 'CAL_REPORT_RECIPIENT_1', 'CAL_REPORT_RECIPIENT_2']:
    if k in data:
        val = base64.b64decode(data[k]).decode()
        print(f'{k}: {val[:4]}...' if len(val) > 4 else f'{k}: SET')
    else:
        print(f'{k}: MISSING — wait and retry')
"
```

Expected: All three keys show as set.

---

### Task 2: Patch cortech-infra Deployment Manifests

Three deployments need env var additions. `osint-core` (API) needs the most changes — it's missing `OSINT_XAI_API_KEY` entirely. Worker and beat already have it but are missing the other CAL-specific vars.

**Files:**
- Modify: `/root/repos/personal/cortech-infra/apps/osint/base/osint-core/deployment.yaml`
- Modify: `/root/repos/personal/cortech-infra/apps/osint/base/osint-worker/deployment.yaml`
- Modify: `/root/repos/personal/cortech-infra/apps/osint/base/osint-beat/deployment.yaml`

- [ ] **Step 1: Add env vars to osint-core deployment**

Add the following entries to the `env:` array in `/root/repos/personal/cortech-infra/apps/osint/base/osint-core/deployment.yaml`, after the `OSINT_LOG_LEVEL` entry (line 72):

```yaml
            - name: OSINT_XAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: XAI_API_KEY
            - name: OSINT_COURTLISTENER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: COURTLISTENER_API_KEY
            - name: OSINT_RESEND_API_KEY
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: RESEND_API_KEY
            - name: CAL_REPORT_RECIPIENT_1
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: CAL_REPORT_RECIPIENT_1
            - name: CAL_REPORT_RECIPIENT_2
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: CAL_REPORT_RECIPIENT_2
```

- [ ] **Step 2: Add env vars to osint-worker deployment**

Add the following entries to the `env:` array in `/root/repos/personal/cortech-infra/apps/osint/base/osint-worker/deployment.yaml`, after the `OSINT_LOG_LEVEL` entry (line 91):

```yaml
            - name: OSINT_COURTLISTENER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: COURTLISTENER_API_KEY
            - name: OSINT_RESEND_API_KEY
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: RESEND_API_KEY
            - name: CAL_REPORT_RECIPIENT_1
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: CAL_REPORT_RECIPIENT_1
            - name: CAL_REPORT_RECIPIENT_2
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: CAL_REPORT_RECIPIENT_2
```

Note: `OSINT_XAI_API_KEY` is already present on worker (line 85-89).

- [ ] **Step 3: Add env vars to osint-beat deployment**

Add the following entries to the `env:` array in `/root/repos/personal/cortech-infra/apps/osint/base/osint-beat/deployment.yaml`, after the `OSINT_LOG_LEVEL` entry (line 91):

```yaml
            - name: OSINT_COURTLISTENER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: COURTLISTENER_API_KEY
            - name: OSINT_RESEND_API_KEY
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: RESEND_API_KEY
            - name: CAL_REPORT_RECIPIENT_1
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: CAL_REPORT_RECIPIENT_1
            - name: CAL_REPORT_RECIPIENT_2
              valueFrom:
                secretKeyRef:
                  name: osint-secrets
                  key: CAL_REPORT_RECIPIENT_2
```

Note: `OSINT_XAI_API_KEY` is already present on beat (line 85-89).

- [ ] **Step 4: Commit and push cortech-infra changes**

```bash
cd /root/repos/personal/cortech-infra
git add apps/osint/base/osint-core/deployment.yaml \
        apps/osint/base/osint-worker/deployment.yaml \
        apps/osint/base/osint-beat/deployment.yaml
git commit -m "feat(osint): add CAL prospecting env vars to all deployments"
git push origin main
```

- [ ] **Step 5: Wait for ArgoCD sync and verify pods are healthy**

ArgoCD will detect the change and roll out new pods. Verify:

```bash
kubectl -n osint rollout status deployment/osint-core --timeout=120s
kubectl -n osint rollout status deployment/osint-worker --timeout=120s
kubectl -n osint rollout status deployment/osint-beat --timeout=120s
```

Expected: All three deployments show `successfully rolled out`.

- [ ] **Step 6: Verify env vars are present in running pods**

```bash
kubectl -n osint exec deploy/osint-worker -- env | grep -E "COURTLISTENER|RESEND|CAL_REPORT|XAI" | sed 's/=.*/=***/'
```

Expected output:
```
OSINT_XAI_API_KEY=***
OSINT_COURTLISTENER_API_KEY=***
OSINT_RESEND_API_KEY=***
CAL_REPORT_RECIPIENT_1=***
CAL_REPORT_RECIPIENT_2=***
```

---

### Task 3: Activate the CAL Prospecting Plan

**Files:** None — API operations only.

- [ ] **Step 1: Sync plans from disk**

```bash
curl -s -X POST https://osint.corbello.io/api/v1/plans:sync-from-disk | python3 -m json.tool
```

Expected: Response includes `cal-prospecting` in the synced plans list with a new version created.

- [ ] **Step 2: Verify plan is active**

```bash
curl -s https://osint.corbello.io/api/v1/plans/cal-prospecting/active-version | python3 -m json.tool
```

Expected: 200 response with `plan_id: "cal-prospecting"`, `activated_at` set, and `content` containing all 14 sources.

- [ ] **Step 3: Verify beat picked up the new plan schedule**

Check beat logs for the dynamic schedule registration:

```bash
kubectl -n osint logs deploy/osint-beat --tail=50 | grep -i "cal-prospecting"
```

Expected: Log lines showing schedule entries like `ingest-cal-prospecting-rss_fire`, etc.

---

### Task 4: Ingest Batch 1 — RSS Sources (4 sources)

**Files:** None — API operations only.

- [ ] **Step 1: Trigger all 4 RSS sources**

```bash
API="https://osint.corbello.io/api/v1"
PLAN="cal-prospecting"

for src in rss_fire rss_higher_ed_dive rss_volokh rss_courthouse_news; do
  echo "--- Triggering $src ---"
  curl -s -X POST "$API/ingest/source/$src/run?plan_id=$PLAN" | python3 -m json.tool
  echo
done
```

Expected: Each returns a JSON response with a `task_id`.

- [ ] **Step 2: Monitor job completion**

Poll until all 4 jobs complete (wait ~2-3 minutes):

```bash
curl -s "$API/jobs?kind=ingest&limit=10" | python3 -c "
import sys, json
jobs = json.loads(sys.stdin.read())
for j in jobs.get('items', jobs) if isinstance(jobs, dict) else jobs:
    src = j.get('input', {}).get('source_id', '?')
    print(f\"{src}: {j.get('status', '?')} — {j.get('event_count', '?')} events\")
"
```

Expected: All 4 RSS sources show `succeeded` status with event counts > 0.

- [ ] **Step 3: Check for failures**

```bash
curl -s "$API/jobs?kind=ingest&status=failed&limit=10" | python3 -m json.tool
```

Expected: Empty list. If any failed, check worker logs:
```bash
kubectl -n osint logs deploy/osint-worker --tail=100 | grep -i "error\|fail\|rss"
```

---

### Task 5: Ingest Batch 2 — xAI x_search Sources (4 sources)

**Files:** None — API operations only.

- [ ] **Step 1: Trigger all 4 xAI x_search sources**

```bash
API="https://osint.corbello.io/api/v1"
PLAN="cal-prospecting"

for src in x_cal_california x_cal_texas x_cal_minnesota x_cal_dc; do
  echo "--- Triggering $src ---"
  curl -s -X POST "$API/ingest/source/$src/run?plan_id=$PLAN" | python3 -m json.tool
  echo
done
```

Expected: Each returns a `task_id`. These take longer than RSS (external API calls to xAI).

- [ ] **Step 2: Monitor job completion (allow ~5 minutes)**

```bash
curl -s "$API/jobs?kind=ingest&limit=20" | python3 -c "
import sys, json
jobs = json.loads(sys.stdin.read())
for j in jobs.get('items', jobs) if isinstance(jobs, dict) else jobs:
    src = j.get('input', {}).get('source_id', '?')
    if 'x_cal' in src:
        print(f\"{src}: {j.get('status', '?')} — {j.get('event_count', '?')} events\")
"
```

Expected: All 4 x_search sources show `succeeded` with event counts > 0.

- [ ] **Step 3: Spot-check xAI events**

Verify the x_search connector produced well-formed events with NLP metadata:

```bash
curl -s "$API/events?plan_id=cal-prospecting&limit=3" | python3 -c "
import sys, json
events = json.loads(sys.stdin.read())
for e in (events.get('items', events) if isinstance(events, dict) else events)[:3]:
    print(f\"Source: {e.get('source_id')} | Title: {e.get('title', 'n/a')[:60]}\")
    meta = e.get('metadata_', {})
    print(f\"  constitutional_basis: {meta.get('constitutional_basis', 'n/a')}\")
    print(f\"  jurisdiction: {meta.get('jurisdiction', 'n/a')}\")
    print()
"
```

Expected: Events with `constitutional_basis` and `jurisdiction` populated from NLP enrichment.

---

### Task 6: Ingest Batch 3 — University Policy Sources (6 sources)

**Files:** None — API operations only.

- [ ] **Step 1: Trigger all 6 university policy sources**

```bash
API="https://osint.corbello.io/api/v1"
PLAN="cal-prospecting"

for src in univ_uc univ_csu univ_ut univ_tamu univ_umn univ_udc; do
  echo "--- Triggering $src ---"
  curl -s -X POST "$API/ingest/source/$src/run?plan_id=$PLAN" | python3 -m json.tool
  echo
done
```

Expected: Each returns a `task_id`. First run baselines all policies — may produce many RawItems.

- [ ] **Step 2: Monitor job completion (allow ~5-10 minutes)**

University policy scraping involves HTTP fetches + potential PDF downloads:

```bash
curl -s "$API/jobs?kind=ingest&limit=20" | python3 -c "
import sys, json
jobs = json.loads(sys.stdin.read())
for j in jobs.get('items', jobs) if isinstance(jobs, dict) else jobs:
    src = j.get('input', {}).get('source_id', '?')
    if 'univ_' in src:
        print(f\"{src}: {j.get('status', '?')} — {j.get('event_count', '?')} events\")
"
```

Expected: Sources show `succeeded`. Some may have 0 events if the policy portal structure doesn't match the CSS selectors — that's expected for a first run and indicates selector tuning may be needed.

- [ ] **Step 3: Check for scraping errors**

```bash
kubectl -n osint logs deploy/osint-worker --tail=200 | grep -i "university_policy\|univ_\|selector\|scrape" | tail -30
```

Note any 403/404 errors or selector mismatches for later tuning.

---

### Task 7: Post-Ingestion Verification

**Files:** None — API operations only.

- [ ] **Step 1: Check total event count**

```bash
curl -s "$API/events?plan_id=cal-prospecting&limit=1" | python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
print(f\"Total events: {data.get('total', data.get('count', len(data.get('items', data))))}\")
"
```

Expected: Non-zero event count.

- [ ] **Step 2: Check leads were created**

```bash
curl -s "$API/leads?plan_id=cal-prospecting&limit=20" | python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
leads = data.get('items', data) if isinstance(data, dict) else data
print(f'Total leads: {len(leads)}')
for l in leads[:10]:
    print(f\"  [{l.get('lead_type')}] [{l.get('severity')}] [{l.get('jurisdiction')}] {l.get('title', 'n/a')[:70]}\")
    print(f\"    confidence={l.get('confidence')} constitutional_basis={l.get('constitutional_basis')}\")
"
```

Expected: Leads with `lead_type` (incident/policy), `severity`, `jurisdiction`, `confidence`, and `constitutional_basis` populated.

- [ ] **Step 3: Check enrichment pipeline completed**

Verify no stuck tasks in the enrichment chain:

```bash
kubectl -n osint exec deploy/osint-worker -- celery -A osint_core.workers.celery_app inspect active 2>/dev/null | head -20
```

Expected: No `match_leads` or `nlp_enrich` tasks still running. If tasks are still active, wait for them to complete before proceeding to report generation.

---

### Task 8: Generate Test Report

**Files:** None — Celery task invocation.

- [ ] **Step 1: Trigger report generation**

```bash
kubectl -n osint exec deploy/osint-worker -- celery -A osint_core.workers.celery_app call osint.generate_prospecting_report
```

Expected: Returns a task ID. The task may defer initially if it detects in-progress `match_leads` tasks (pipeline guard).

- [ ] **Step 2: Monitor report generation**

```bash
kubectl -n osint logs deploy/osint-worker --tail=100 -f | grep -i "prospecting_report\|report_gen\|resend\|weasyprint\|minio"
```

Watch for:
- "Generating prospecting report" — task started
- "report_leads_selected" — leads being included
- "courtlistener_verify" — citation verification
- "weasyprint_render" — PDF rendering
- "minio_upload" — PDF archived
- "resend_email_sent" — email delivered

Expected: Complete pipeline with email delivery confirmation.

- [ ] **Step 3: Check for report generation errors**

If the task fails or defers repeatedly:

```bash
kubectl -n osint logs deploy/osint-worker --tail=200 | grep -iE "error|traceback|fail|retry|defer" | tail -20
```

Common issues:
- "no reportable leads" — confidence threshold too high (currently 0.3), or leads not created
- "resend_no_api_key" — `OSINT_RESEND_API_KEY` not set on the worker pod
- WeasyPrint rendering error — template issue
- Pipeline guard deferral — enrichment still in progress, will auto-retry

---

### Task 9: Review Report Output

- [ ] **Step 1: Check email inbox**

Check the email address set in `CAL_REPORT_RECIPIENT_1` for a message from `reports@corbello.io` with subject starting with "CAL Prospecting Report".

Expected: Email with plain-text executive summary in body and PDF attachment.

- [ ] **Step 2: Review PDF contents**

Open the attached PDF and verify:

- Cover page: correct branding, date, report period
- Executive summary: lead counts by type (incident/policy) and jurisdiction (CA/TX/MN/DC)
- Lead sections: structured per the design spec (summary, constitutional analysis, parties, evidence, citations)
- Citations appendix: source material with URLs + legal citations with verification status
- No hallucinated legal citations

- [ ] **Step 3: Verify leads updated in DB**

```bash
curl -s "$API/leads?plan_id=cal-prospecting&limit=20" | python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
leads = data.get('items', data) if isinstance(data, dict) else data
for l in leads[:5]:
    print(f\"  status={l.get('status')} reported_at={l.get('reported_at')} report_id={l.get('report_id')}\")
"
```

Expected: Leads that were included in the report show `status: 'reviewing'`, `reported_at` set, and `report_id` populated.

- [ ] **Step 4: Verify PDF archived in MinIO**

```bash
kubectl -n osint exec deploy/osint-worker -- python3 -c "
from osint_core.config import settings
from minio import Minio
client = Minio(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, secure=settings.minio_secure)
objects = list(client.list_objects('artifacts', prefix='prospecting-reports/', recursive=True))
for o in objects[-3:]:
    print(f'{o.object_name} — {o.size} bytes — {o.last_modified}')
"
```

Expected: At least one PDF object in the `prospecting-reports/` prefix.

---

### Task 10: Post-Test Decision

- [ ] **Step 1: Document findings**

Record:
- Total events ingested per source type
- Total leads created
- Any sources that failed or returned 0 events
- PDF quality assessment
- Any tuning needed (search queries, confidence threshold, CSS selectors)

- [ ] **Step 2: If satisfactory — swap recipients to CAL**

Update Infisical `/osint` path:

```bash
infisical secrets set CAL_REPORT_RECIPIENT_1="<cal-recipient-email>" --env=prod --path=/osint
infisical secrets set CAL_REPORT_RECIPIENT_2="<cal-recipient-email-2>" --env=prod --path=/osint
```

Wait 60s for Infisical sync, then restart worker to pick up new values:

```bash
kubectl -n osint rollout restart deployment/osint-worker
```

The Celery Beat static schedule will handle ongoing collection (07:00/14:00 CT) and report generation (08:00/15:00 CT) automatically.

- [ ] **Step 3: If tuning needed — adjust plan YAML and re-test**

Edit `plans/cal-prospecting.yaml` in the osint-core repo:
- Search queries: modify `searches` arrays in xAI sources
- Confidence threshold: modify `custom.lead_confidence_threshold` (currently 0.3)
- CSS selectors: modify `selector` in university_policy sources
- Scoring weights: modify `scoring.source_reputation` values

Commit, push, wait for CI to deploy, then re-run from Task 3 (plan sync + full ingestion cycle).
