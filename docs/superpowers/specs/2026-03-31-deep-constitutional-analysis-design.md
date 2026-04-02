# Deep Constitutional Analysis — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Scope:** New pipeline stage between lead matching and report generation that performs clause-level constitutional analysis of full policy documents and corroboration assessment of incident leads, producing actionable output for CAL attorneys.

---

## Problem Statement

The current pipeline produces shallow, unactionable output. Policy leads reference a policy title and add a vague "this might be a First Amendment issue" comment. Incident leads summarize the event without assessing corroboration strength. Neither is useful for attorneys deciding whether to pursue a case.

The root cause is that no step in the pipeline reads the full source material. The NLP enrichment stage sees only the first 500 characters. The narrative generation stage sees only the lead's summary and metadata. Full policy documents are archived in MinIO but never analyzed.

---

## Design

### Pipeline Position

New stage between lead matching and report generation:

```
Collection → Event Creation → NLP Enrichment → Lead Matching → Deep Analysis → Report Generation
```

Triggered as a Celery task after `match_leads` completes. Processes every new lead that has an archived document. The task resolves the source document by looking up the lead's `event_ids`, finding the corresponding events, and extracting `minio_uri` from `event.raw_data` (set by the university policy connector during archival). For incident leads without a `minio_uri`, the task uses the event's `raw_content` or fetches the source URL directly. Configurable via plan YAML:

```yaml
custom:
  deep_analysis_enabled: true
  deep_analysis_relevance_gate: false  # true = only analyze leads with relevance='relevant'
```

When `deep_analysis_relevance_gate` is `true`, only leads whose source event was classified as `relevant` (not `tangential` or `irrelevant`) during NLP enrichment get the deep analysis. Default is `false` (analyze everything).

---

### Document Processing

**Text extraction:**

- **HTML:** BeautifulSoup `get_text()` with section header preservation — `<h1>`–`<h6>` tags are converted to markdown-style markers (`## Section Title`) so the LLM knows which section it's reading.
- **PDF:** PyMuPDF (`fitz`) — extract text page-by-page, preserving page numbers as markers (`[Page 3]`).

**Chunking:**

- Documents under ~80k tokens (~300k characters) are analyzed in a single pass.
- Documents over the threshold are chunked:
  - **Chunk size:** ~60k tokens (~240k chars) with ~5k token overlap.
  - **Split priority:** Section boundaries (§, Article, Section, Rule, heading markers) → paragraph boundaries → hard character split.
  - **Chunk preamble:** Each chunk includes the document title, institution name, and a table of contents (all section headings extracted from the full document) so the LLM knows where the chunk sits.
- **Chunk synthesis:** Each chunk produces its own list of identified provisions. After all chunks complete, a mechanical dedup/merge pass combines findings — provisions referencing the same section number from overlapping chunks are deduplicated. No synthesis LLM call.

**Implementation:**

`DocumentExtractor` service (`src/osint_core/services/document_extractor.py`) handles text extraction and chunking. Separated from the analysis service for reuse in future non-CAL analysis workflows.

---

### Analysis Prompts and Structured Output

#### Policy Leads

The LLM acts as a constitutional law clerk reviewing a policy document for The Center For American Liberty. It must:

1. Identify specific provisions that restrict, burden, or implicate constitutional rights
2. Quote the exact language from the document
3. Reference the section/rule number
4. Classify which right is affected
5. Assess severity
6. Note the affected population
7. Assess whether the issue is a facial challenge or as-applied

**Groq strict structured output schema:**

```json
{
  "type": "object",
  "properties": {
    "provisions": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "section_reference": { "type": "string" },
          "quoted_language": { "type": "string" },
          "constitutional_issue": { "type": "string" },
          "constitutional_basis": {
            "enum": ["1A-free-speech", "1A-religion", "1A-assembly", "1A-press",
                     "14A-due-process", "14A-equal-protection", "parental-rights"]
          },
          "severity": { "enum": ["info", "low", "medium", "high", "critical"] },
          "affected_population": { "type": "string" },
          "facial_or_as_applied": { "enum": ["facial", "as-applied", "both"] }
        },
        "required": ["section_reference", "quoted_language", "constitutional_issue",
                     "constitutional_basis", "severity", "affected_population",
                     "facial_or_as_applied"],
        "additionalProperties": false
      }
    },
    "document_summary": { "type": "string" },
    "overall_assessment": { "type": "string" },
    "actionable": { "type": "boolean" }
  },
  "required": ["provisions", "document_summary", "overall_assessment", "actionable"],
  "additionalProperties": false
}
```

If the document contains no constitutional issues, `provisions` is an empty array and `actionable` is `false`. The lead gets downgraded rather than appearing in the report with vague language.

#### Incident Leads

For incident leads (news articles, social media posts), the analysis fetches the article/post content from the event's raw data and produces a corroboration assessment.

**Schema:**

```json
{
  "type": "object",
  "properties": {
    "incident_summary": { "type": "string" },
    "rights_violated": {
      "type": "array",
      "items": {
        "enum": ["1A-free-speech", "1A-religion", "1A-assembly", "1A-press",
                 "14A-due-process", "14A-equal-protection", "parental-rights"]
      }
    },
    "individuals_identified": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "role": { "type": "string" }
        },
        "required": ["name", "role"],
        "additionalProperties": false
      }
    },
    "institution": { "type": "string" },
    "corroboration_strength": { "enum": ["strong", "moderate", "weak", "unverified"] },
    "corroboration_notes": { "type": "string" },
    "actionable": { "type": "boolean" }
  },
  "required": ["incident_summary", "rights_violated", "individuals_identified",
               "institution", "corroboration_strength", "corroboration_notes", "actionable"],
  "additionalProperties": false
}
```

---

### CourtListener Precedent Matching

For each constitutional basis identified in the deep analysis, attach verified case law citations.

**Strategy: Known landmarks + targeted search.**

A lookup table of landmark cases per constitutional basis and sub-issue lives in the plan YAML under `custom.precedent_map`:

```yaml
custom:
  precedent_map:
    1A-free-speech:
      compelled_speech:
        - case: "West Virginia State Board of Education v. Barnette"
          citation: "319 U.S. 624 (1943)"
        - case: "Janus v. AFSCME"
          citation: "585 U.S. 878 (2018)"
        - case: "303 Creative LLC v. Elenis"
          citation: "600 U.S. 570 (2023)"
      speech_codes:
        - case: "Tinker v. Des Moines Independent Community School District"
          citation: "393 U.S. 503 (1969)"
        - case: "Healy v. James"
          citation: "408 U.S. 169 (1972)"
        - case: "Papish v. Board of Curators"
          citation: "410 U.S. 667 (1973)"
      viewpoint_discrimination:
        - case: "Rosenberger v. Rector and Visitors of the University of Virginia"
          citation: "515 U.S. 819 (1995)"
        - case: "Board of Regents of the University of Wisconsin System v. Southworth"
          citation: "529 U.S. 217 (2000)"
    1A-religion:
      free_exercise:
        - case: "Kennedy v. Bremerton School District"
          citation: "597 U.S. 507 (2022)"
        - case: "Fulton v. City of Philadelphia"
          citation: "593 U.S. 522 (2021)"
    14A-due-process:
      campus_discipline:
        - case: "Mathews v. Eldridge"
          citation: "424 U.S. 319 (1976)"
        - case: "Goss v. Lopez"
          citation: "419 U.S. 565 (1975)"
        - case: "Doe v. Baum"
          citation: "903 F.3d 575 (6th Cir. 2018)"
    14A-equal-protection:
      general:
        - case: "Reed v. Reed"
          citation: "404 U.S. 71 (1971)"
    parental-rights:
      general:
        - case: "Troxel v. Granville"
          citation: "530 U.S. 57 (2000)"
        - case: "Pierce v. Society of Sisters"
          citation: "268 U.S. 510 (1925)"
```

**Flow per provision:**

1. Match the provision's `constitutional_basis` + `constitutional_issue` keywords to the appropriate sub-category in the precedent map
2. Select the 2-3 most relevant landmarks
3. Verify each against CourtListener API — confirm citation format, retrieve holding summary
4. If the LLM's analysis mentions a specific case name not in the table, attempt to verify that case via CourtListener too
5. Attach verified citations to the provision

Attorneys can add or remove cases from `precedent_map` in the plan YAML without code changes.

---

### Lead Model Changes

**New columns on `leads` table:**

| Column | Type | Description |
|--------|------|-------------|
| `deep_analysis` | JSONB (nullable) | Full analysis output (provisions or corroboration assessment) |
| `analysis_status` | String | `pending`, `completed`, `no_source_material`, `failed` |

Default `analysis_status` is `pending`. Set to `completed` after successful deep analysis, `no_source_material` when no archived document or article content is retrievable, `failed` on LLM or processing errors.

Requires an Alembic migration.

**Index:**
- `ix_leads_analysis_status` for filtering during report generation.

---

### Report Integration

Report generation changes based on `analysis_status`:

**When `analysis_status == 'completed'`:**

- **Policy leads:** Render provisions directly — quoted language, section refs, constitutional issue, severity, facial/as-applied assessment, and verified precedent citations. No LLM narrative call needed.
- **Incident leads:** Render corroboration assessment — who was harmed, what right, institution, strength of evidence, cited sources.

**When `analysis_status != 'completed'`:**

Fall back to current narrative generation (shallow summary + fallback).

**Leads where `actionable == false`** in deep analysis are excluded from the report entirely — they would only add noise. Their `severity` is downgraded to `info` so they don't trigger notifications.

**Example report output for a policy lead (before → after):**

Before:
> "The University of Texas System has updated its Policy Library with new policies, including those related to free speech. This might be a First Amendment issue."

After:
> **§ 4.2.1 — Compelled Speech**
> *"Students must use the preferred name and pronouns of any individual upon request. Failure to comply constitutes harassment under Policy 12.3."*
>
> This provision compels speech in violation of the First Amendment. See *West Virginia v. Barnette*, 319 U.S. 624 (1943); *303 Creative LLC v. Elenis*, 600 U.S. 570 (2023).
>
> **Severity:** High — facial challenge viable
> **Affected population:** All enrolled students

---

### New Components

| Component | Type | Path |
|-----------|------|------|
| `DeepAnalyzer` | Service | `src/osint_core/services/deep_analyzer.py` |
| `DocumentExtractor` | Service | `src/osint_core/services/document_extractor.py` |
| Deep analysis migration | Migration | `migrations/versions/XXXX_add_deep_analysis.py` |
| `analyze_lead_task` | Worker task | `src/osint_core/workers/prospecting.py` |

### Modified Components

| Component | Change |
|-----------|--------|
| `src/osint_core/models/lead.py` | Add `deep_analysis` JSONB + `analysis_status` columns |
| `src/osint_core/workers/prospecting.py` | Wire `analyze_lead_task` after `match_leads`, before report generation |
| `src/osint_core/services/prospecting_report.py` | Render deep analysis when available, skip narrative LLM call |
| `src/osint_core/templates/prospecting_report.html` | New template sections for provisions and corroboration |
| `src/osint_core/services/courtlistener.py` | Add `lookup_precedent()` method for precedent map matching |
| `plans/cal-prospecting.yaml` | Add `precedent_map`, `deep_analysis_enabled`, `deep_analysis_relevance_gate` |

---

### Cost and Performance

- **Groq gpt-oss-20b:** $0.075/1M input, $0.30/1M output tokens
- **Typical policy:** ~5-20k tokens input, ~1k tokens output ≈ $0.001-0.002 per policy
- **Large policy (128k):** ~$0.01 per analysis
- **Per cycle:** ~10-30 policies = $0.01-0.06 per cycle, $0.04-0.24/day
- **CourtListener:** Free REST API, rate-limited. ~2-3 lookups per provision, well within limits.
- **Wall-clock time:** ~2-5 seconds per policy on Groq (1000 tok/s). Chunked documents ~5-15 seconds. Total cycle addition: ~1-3 minutes.
