# CAL Constitutional Prospecting — Design Spec

**Date:** 2026-03-27
**Status:** Draft
**Scope:** New prospecting subsystem for The Center For American Liberty (libertycenter.org) that identifies potential constitutional law clients through two angles: (1) individuals whose rights have been violated, and (2) unconstitutional policies at state universities. Covers CA, MN, TX, and DC.

---

## Problem Statement

The Center For American Liberty needs a systematic way to identify potential clients for constitutional litigation. Today this is manual — attorneys and staff monitor news, social media, and tip lines. The OSINT platform can automate this by continuously collecting signals from X/Twitter, state university policy portals, and legal news sources, then deduplicating, enriching, and packaging them into professional reports delivered twice daily.

---

## Two Prospecting Angles

### Angle 1: People Who Have Been Harmed (Incidents)

Individuals whose constitutional rights have been violated by state institutions. Signal types:

- Students/faculty punished for speech or expression on campus
- Parents facing overreach from schools (forced medical decisions, gender policy conflicts, parental notification bypasses)
- Religious expression suppressed at state universities
- Retaliation for political viewpoints at state institutions
- Due process violations in campus disciplinary proceedings

**Primary source:** xAI x_search (X/Twitter), corroborated by legal news RSS.

### Angle 2: Unconstitutional Policies

State university policies that facially violate the First Amendment, parental rights, or related constitutional protections. Examples:

- Speech codes that restrict protected expression
- Mandatory pronoun or DEI compliance policies
- Policies bypassing parental notification/consent
- Religious accommodation denials codified in policy
- Viewpoint-discriminatory funding or recognition policies

**Primary source:** University policy portal scraping, corroborated by FIRE reports, legal news.

---

## Geographic Scope

| State | Target Institutions | Notes |
|-------|-------------------|-------|
| California | UC system, CSU system | Largest state university systems |
| Texas | UT system, Texas A&M system | Recent legislative activity on campus speech |
| Minnesota | University of Minnesota system | Board of Regents policies |
| DC | University of the District of Columbia | Federal-adjacent jurisdiction |

---

## Architecture

### Lead Model

The `Lead` is the core new entity — a deduplicated prospecting opportunity moving through a qualification pipeline.

**Table: `leads`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `lead_type` | Enum | `incident` or `policy` |
| `status` | Enum | `new`, `reviewing`, `qualified`, `contacted`, `retained`, `declined`, `stale` |
| `title` | str | Human-readable summary |
| `summary` | text | AI-generated, citation-backed narrative |
| `constitutional_basis` | ARRAY[str] | e.g., `["1A-free-speech", "14A-due-process"]` |
| `jurisdiction` | str | `CA`, `TX`, `MN`, or `DC` |
| `institution` | str | e.g., `University of Minnesota` |
| `severity` | Enum | `info`, `low`, `medium`, `high`, `critical` |
| `confidence` | float | 0.0–1.0, strength of signal |
| `dedupe_fingerprint` | str (unique) | Hash of `(lead_type, institution, normalized_key)` |
| `plan_id` | str | Which plan generated this lead |
| `event_ids` | ARRAY[UUID] | Source events that contributed |
| `entity_ids` | ARRAY[UUID] | People, orgs involved |
| `citations` | JSONB | Verified legal + source citations (structure below) |
| `report_id` | UUID (nullable) | Which PDF report included this lead |
| `first_surfaced_at` | datetime | When first detected |
| `last_updated_at` | datetime | When new evidence last attached |
| `reported_at` | datetime (nullable) | When emailed to CAL |
| `created_at` | datetime | Row creation |
| `updated_at` | datetime | Row update |

**Deduplication:** `dedupe_fingerprint = sha256(lead_type + institution + normalized_policy_name_or_incident_key)`. New events about the same policy or incident attach to the existing Lead (appended to `event_ids`) rather than creating a duplicate. If new evidence arrives after a Lead has been reported, `last_updated_at` bumps and the Lead re-enters the next report cycle as "updated."

**Indexes:**
- `ix_leads_dedupe_fingerprint` (unique)
- `ix_leads_status` (filtering)
- `ix_leads_jurisdiction` (filtering)
- `ix_leads_reported_at` (report cycle queries)
- `ix_leads_plan_id` (plan association)

### Citations Structure (JSONB)

```json
{
  "source_citations": [
    {
      "ref_id": 1,
      "type": "social_media | policy_document | news_article | government_record",
      "title": "Human-readable title",
      "url": "https://...",
      "section": "§3.2 — optional section reference",
      "accessed_at": "2026-03-26T14:00:00Z",
      "archived_artifact_id": "uuid — link to archived copy in MinIO"
    }
  ],
  "legal_citations": [
    {
      "ref_id": 2,
      "type": "case_law | statute | constitutional_provision",
      "case_name": "Tinker v. Des Moines Independent Community School District",
      "citation": "393 U.S. 503 (1969)",
      "courtlistener_url": "https://www.courtlistener.com/opinion/...",
      "verified": true,
      "relevance": "One-line explanation of why this citation matters"
    }
  ]
}
```

**Rules:**
- Every factual claim in the report maps to a numbered citation.
- Source material is archived as Artifacts (`retention_class: evidentiary`) to prevent link rot.
- Legal citations are only included if verified against CourtListener API or a known statute database.
- Unverifiable references are flagged as "cited in source material, not independently verified."
- LLMs never generate legal citations — only citations found in collected source material are used.

---

## Data Sources & Connectors

### 1. xAI x_search (Existing Connector, New Plan Config)

Configured with CAL-specific searches. Queries scoped by:
- Institution-specific terms (e.g., "UC Berkeley suspended," "UT Austin policy")
- Known handles: FIRE, state ACLU chapters, campus reform outlets, reporters on the beat
- Short lookback windows (12 hours, matching the twice-daily cycle)
- Jurisdiction-specific geo terms

The `mission` prompt tells Grok the context for The Center For American Liberty's focus areas. Query tuning is managed in plan YAML — no code changes needed to refine searches.

### 2. University Policy Connector (New)

**New file:** `src/osint_core/connectors/university_policy.py`
**Registration:** `university_policy` in connector registry.

Scrapes state university policy portals for new or changed policies:

1. Fetches policy index/listing pages for each configured institution
2. Diffs against last run (by URL + content hash) to detect new/changed policies
3. Downloads policy documents (HTML or PDF)
4. Archives as Artifacts (`retention_class: evidentiary`)
5. Produces one `RawItem` per new/changed policy

**Plan config shape:**
```yaml
- id: uc_system_policies
  type: university_policy
  params:
    institutions:
      - name: "University of California"
        policy_url: "https://policy.ucop.edu/..."
        selector: "css selector for policy links"
      - name: "California State University"
        policy_url: "https://..."
    lookback_days: 7
    archive_pdfs: true
```

Each institution's portal has a different structure, so the connector accepts CSS selectors or configurable parsing rules per institution. Initial implementation covers the specific portals for the 4 target states; new institutions are added via plan config.

### 3. CourtListener Client (New Service, Not a Connector)

**New file:** `src/osint_core/services/courtlistener.py`

A verification service, not a collection source. Called during report generation to:
- Confirm case names and get correct citation format via CourtListener's free REST API
- Pull relevant holding/summary text
- Return a verification result (verified/not found/ambiguous)

Rate-limited to respect CourtListener's API terms.

### 4. Legal News RSS (Existing Connector, New Plan Config)

RSS feeds configured in the plan YAML:
- FIRE (thefire.org) — campus speech and expression
- Reason / Volokh Conspiracy — constitutional law commentary
- Courthouse News Service — litigation coverage
- State-specific legal outlets as identified

Uses the existing RSS connector with no code changes.

---

## Processing Pipeline

```
Collection (cron: ~7:00 AM and ~2:00 PM CST, allowing processing time)
│
├── xAI x_search → RawItems (incidents, posts)
├── University Policy Scraper → RawItems (new/changed policies)
└── Legal News RSS → RawItems (articles)
│
▼
Event Creation & Deduplication (existing pipeline)
│
▼
NLP Enrichment (existing, with prompt tuning)
├── Entity extraction: people, institutions, officials
├── Classification: which constitutional rights are implicated
│   (new labels: 1A-free-speech, 1A-religion, 1A-assembly,
│    14A-due-process, parental-rights, equal-protection)
├── Jurisdiction tagging: CA / TX / MN / DC
└── Severity assessment: egregiousness of violation
│
▼
Lead Matching (new service)
├── Does this event match an existing Lead? (dedupe_fingerprint)
│   ├── YES → attach event, bump last_updated_at
│   └── NO  → create new Lead
├── Lead confidence scoring (source count, corroboration, severity)
└── Filter: only Leads with confidence ≥ threshold proceed
│
▼
Citation Verification (new service)
├── Extract case law / statute references from source material
├── Verify against CourtListener API
├── Collect source material URLs (policy docs, posts, articles)
└── Package into structured citations JSON on the Lead
│
▼
Report Generation (new service, runs at 8:00 AM and 3:00 PM CST)
├── Select Leads where status = "new" OR (status = "reviewing" AND last_updated_at > reported_at)
├── Generate consolidated PDF via WeasyPrint
├── Archive PDF as Artifact (retention_class: evidentiary)
├── Mark Leads: reported_at = now, status → "reviewing"
└── Send PDF via Resend to configured recipients
```

---

## Report Format

One consolidated PDF per report cycle. Structure:

### Cover Page
- The Center For American Liberty branding
- Report title: "Constitutional Prospecting Report"
- Date and time (CST)
- Report period (since last report)

### Executive Summary
- Count of new leads and updated leads
- Breakdown by type (incident vs. policy) and jurisdiction
- Highest-priority items flagged

### Lead Sections (one per lead)

**Incident leads:**
1. Executive summary — who, what happened, where
2. Constitutional analysis — which rights violated, relevant precedents
3. Parties involved — individual, institution, officials
4. Evidence summary — source links, social media posts, news articles
5. Jurisdiction & venue analysis
6. Time sensitivity — statute of limitations considerations
7. Recommendation — strength of case assessment
8. Citations — numbered references to appendix

**Policy leads:**
1. Executive summary — what policy, which institution
2. Constitutional analysis — facial challenge viability, as-applied concerns
3. Affected population scope
4. Policy text excerpts with direct links to source document
5. Comparable precedents — similar policies struck down
6. Jurisdiction & venue analysis
7. Recommendation
8. Citations — numbered references to appendix

### Citations Appendix
- **Source Material** — numbered list with title, URL, access date, archived artifact reference
- **Legal Citations** — numbered list with case name, citation, CourtListener URL, verification status, relevance note

---

## Email Delivery

**Service:** Resend API (`src/osint_core/services/resend_notifier.py`)

- Sends at 8:00 AM and 3:00 PM CST
- PDF attached to email
- Email body contains a plain-text executive summary (same content as the PDF executive summary)
- Recipient list configured in plan YAML
- If no new leads in a cycle, no email is sent (no empty reports)

---

## New Components

| Component | Type | Path |
|-----------|------|------|
| `Lead` model | Model | `src/osint_core/models/lead.py` |
| Lead migration | Migration | `migrations/versions/XXXX_add_leads.py` |
| `UniversityPolicyConnector` | Connector | `src/osint_core/connectors/university_policy.py` |
| `CourtListenerClient` | Service | `src/osint_core/services/courtlistener.py` |
| `LeadMatcher` | Service | `src/osint_core/services/lead_matcher.py` |
| `ProspectingReportGenerator` | Service | `src/osint_core/services/prospecting_report.py` |
| `ResendNotifier` | Service | `src/osint_core/services/resend_notifier.py` |
| Lead API routes | API | `src/osint_core/api/routes/leads.py` |
| Report generation task | Worker | `src/osint_core/workers/prospecting.py` |
| `cal-prospecting.yaml` | Plan | `plans/cal-prospecting.yaml` |
| PDF template | Template | `src/osint_core/templates/prospecting_report.html` |

## Reused Components

| Component | Notes |
|-----------|-------|
| `XaiXSearchConnector` | New plan config only |
| `RSSConnector` | New plan config only |
| Event pipeline | Ingestion, dedup, storage — as-is |
| NLP enrichment | Prompt tuning for legal domain classification |
| Artifact storage | MinIO archival of policy docs, screenshots |
| Scoring engine | Prospecting-specific weights in plan YAML |

## Modified Components

| Component | Change |
|-----------|--------|
| NLP enrichment prompts | Add constitutional rights classification labels |
| Plan schema | Extend to support prospecting-specific config (lead thresholds, report schedule, Resend config) |
| Connector registry | Register `university_policy` connector |

---

## Schedule

| Time (CST) | Action |
|------------|--------|
| ~7:00 AM | Collection runs: xAI x_search, university policy scraper, RSS |
| ~7:00–7:50 AM | Enrichment, lead matching, citation verification |
| 8:00 AM | Report generated and emailed |
| ~2:00 PM | Collection runs (second cycle) |
| ~2:00–2:50 PM | Enrichment, lead matching, citation verification |
| 3:00 PM | Report generated and emailed |

---

## Configuration

All tunable via `plans/cal-prospecting.yaml`:
- Search queries and handles for xAI x_search
- University institution list and policy portal URLs
- RSS feed URLs
- Constitutional rights classification labels
- Lead confidence threshold for reporting
- Resend API key and recipient list
- Report schedule (cron expressions)
- Scoring weights

---

## Out of Scope (Future)

- Lead pipeline management UI (status tracking beyond new → reviewing)
- CRM integration
- Additional jurisdictions beyond CA, TX, MN, DC
- Non-university sources (state agencies, school boards, legislation trackers)
- Court docket monitoring (PACER integration)
- Automated statute of limitations calculation
