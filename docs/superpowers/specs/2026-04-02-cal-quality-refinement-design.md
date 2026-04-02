# CAL Prospecting Quality Refinement — Design Spec

**Date:** 2026-04-02
**Status:** Approved
**Scope:** Quality refinement of the CAL prospecting pipeline — two-pass analysis architecture, pre-analysis quality gates, enriched LLM context with source citations, report template improvements, source configuration changes, and new connectors for legislature tracking and OCR complaints.

**Supersedes (partial):** Deep analysis sections of `2026-03-31-deep-constitutional-analysis-design.md`. The analysis pipeline architecture, chunking strategy, and prompt design described here replace the corresponding sections in that spec. All other sections (lead model, CourtListener integration, report integration pattern) remain valid unless explicitly overridden below.

---

## Problem Statement

The first production report (cal-report-20260402-0200) exposed systemic quality issues that trace back to design-level problems in the deep analysis pipeline, not just implementation bugs:

1. **Contradictory analysis.** Overall assessment says "no constitutional issues" while individual provisions are flagged as high severity. Root cause: chunks analyzed in isolation produce inconsistent results because no single LLM call sees the entire document.
2. **No source citations.** Zero policy URLs or legal precedent citations appear in the report. Attorneys cannot verify any finding. Root cause: source URLs and precedent are never passed to the LLM, and the `citations` JSONB on leads is not populated.
3. **Garbled text.** PDF extraction produces boxes/squares on some documents (encoding failures in PyMuPDF). No quality gate catches this before the text hits Groq.
4. **Non-English documents.** Tagalog policy text appears verbatim in the report. No language detection step exists.
5. **"Policy text was not provided."** Groq repeatedly states it cannot analyze text that wasn't provided. Likely a silent failure in MinIO retrieval or text extraction.
6. **Low signal-to-noise ratio.** 19 leads, 27 pages, but only 1 high-priority lead. Employment policies, gift policies, and administrative procedures are not filtered out by the NLP relevance gate.
7. **Broken severity rollup.** All policy leads show INFO severity despite containing high/critical provisions. Lead-level severity does not reflect provision-level findings.
8. **Empty confidence bars.** The percentage value is rendered but the visual bar is never filled.
9. **Raw scraper titles.** Lead titles are literal page titles from the scraper (e.g., `[University of California System] View PolicyRestrictions on...`) rather than descriptive lead titles.

---

## Phase 1: Pipeline Quality

### 1.1 Two-Pass Analysis Architecture

Replaces the current single-pass chunked analysis with a two-pass approach that ensures document-level coherence.

#### Pass 1 — Screening (Full Document)

Send the complete document text to Groq in a single call. For most university policies (5k-80k tokens), this fits within gpt-oss-20b's context window.

**Prompt role:** Constitutional law clerk performing initial review.

**Input:**
- Full document text
- Institution name, jurisdiction
- Document source URL

**Output schema (lightweight):**

```json
{
  "type": "object",
  "properties": {
    "relevant": { "type": "boolean" },
    "language": { "type": "string" },
    "lead_title": { "type": "string" },
    "document_summary": { "type": "string" },
    "overall_assessment": { "type": "string" },
    "flagged_sections": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "section_reference": { "type": "string" },
          "reason": { "type": "string" },
          "constitutional_basis": {
            "enum": ["1A-free-speech", "1A-religion", "1A-assembly", "1A-press",
                     "14A-due-process", "14A-equal-protection", "parental-rights"]
          }
        },
        "required": ["section_reference", "reason", "constitutional_basis"],
        "additionalProperties": false
      }
    }
  },
  "required": ["relevant", "language", "lead_title", "document_summary",
               "overall_assessment", "flagged_sections"],
  "additionalProperties": false
}
```

**Behavior:**
- If `relevant == false` and `flagged_sections` is empty: mark lead as `analysis_status: 'not_actionable'`, downgrade severity to `info`, exclude from report.
- If `language` is not English: mark as `analysis_status: 'non_english'`, skip Pass 2.
- If `relevant == true` or `flagged_sections` is non-empty: proceed to Pass 2 for each flagged section.
- `lead_title` replaces the raw scraper title on the lead.

#### Pass 2 — Targeted Provision Analysis (Per Flagged Section)

For each section flagged in Pass 1, extract that section's text with surrounding context (~2k chars before and after the section boundary) and send it for deep analysis.

**Section extraction strategy:** Use the `section_reference` from Pass 1 to locate the section in the full document text via substring match on the section header/number. If exact match fails, fall back to fuzzy matching (normalized whitespace, case-insensitive). If no match is found, extract a window around the approximate position (character offset proportional to the section's position in the flagged list). Log extraction failures for monitoring.

**Prompt role:** Constitutional law clerk performing detailed provision analysis for The Center For American Liberty.

**Input:**
- Section text with surrounding context
- Institution name, jurisdiction, document title, document source URL
- Corroborating events summary (see Section 1.2)
- Relevant precedent from precedent map (see Section 1.2)

**Output schema (per section, same as current spec with additions):**

```json
{
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
    "facial_or_as_applied": { "enum": ["facial", "as-applied", "both"] },
    "sources_cited": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": { "enum": ["policy_document", "precedent", "corroborating_event"] },
          "url": { "type": "string" },
          "citation": { "type": "string" },
          "section": { "type": "string" }
        },
        "required": ["type"],
        "additionalProperties": false
      }
    }
  },
  "required": ["section_reference", "quoted_language", "constitutional_issue",
               "constitutional_basis", "severity", "affected_population",
               "facial_or_as_applied", "sources_cited"],
  "additionalProperties": false
}
```

#### Fallback for Very Large Documents (>80k tokens)

Documents exceeding the context window are chunked for Pass 1 only:
- Chunk size: ~60k tokens (~240k chars) with ~5k token overlap (per original spec).
- Each chunk gets the Pass 1 screening treatment.
- Flagged sections from all chunks are deduplicated by section reference.
- Pass 2 runs on each unique flagged section as normal.
- Document-level summary and overall assessment are synthesized from chunk summaries in a final lightweight call.

#### Incident Lead Analysis

Incident leads continue to use a single-pass analysis (no two-pass needed — they're typically short-form content). The prompt is enriched with corroborating events and precedent per Section 1.2.

**Input additions:**
- All corroborating event summaries with source URLs
- Relevant precedent based on rights classification from NLP enrichment

**Output schema additions:**
- `sources_cited` array (same structure as policy provisions)

---

### 1.2 Enriched LLM Context

All Groq prompts (Pass 1, Pass 2, incident analysis) include structured context blocks.

#### Source Metadata Block

Always included:

```
--- SOURCE DOCUMENT ---
Institution: {institution}
Jurisdiction: {jurisdiction}
Document title: {title}
Source URL: {source_url}
Date accessed: {accessed_at}
Archived copy: {minio_uri}
```

#### Corroborating Events Block

When a lead has multiple events in `event_ids`, include a summary of each (up to 5, prioritized by recency):

```
--- CORROBORATING SOURCE {n} ---
Type: {news_article | social_media | policy_document}
Title: {event.title}
URL: {event source URL from metadata}
Summary: {event.raw_excerpt, first 500 chars}
Date: {event.created_at}
```

#### Precedent Context Block

For Pass 2 provision analysis, include 2-3 landmark cases from the precedent map matching the `constitutional_basis` identified in Pass 1:

```
--- RELEVANT PRECEDENT ---
- {case_name}, {citation} — {one-line relevance}
- {case_name}, {citation} — {one-line relevance}
```

The precedent map remains in `cal-prospecting.yaml` under `custom.precedent_map` (unchanged from current spec). CourtListener verification remains a post-analysis step — after Groq cites a case, we verify it. But providing curated precedent as input reduces hallucination risk.

---

### 1.3 Pre-Analysis Quality Gates

After text extraction, before Pass 1 screening:

1. **Encoding validation.** Compute ratio of replacement characters (U+FFFD), control characters, and private-use-area codepoints in extracted text. If >5% of characters are garbled, mark as `analysis_status: 'extraction_failed'` with diagnostic message. Do not send to Groq.

2. **Language detection.** Run `langdetect` (or equivalent lightweight detector) on the first 1000 characters of extracted text. If detected language is not English with >80% confidence, mark as `analysis_status: 'non_english'`. Skip analysis. (Pass 1 also returns language as a secondary check, but the pre-gate avoids wasting a Groq call.)

3. **Empty/minimal content check.** If extracted text is under 100 characters after stripping whitespace, mark as `analysis_status: 'no_content'`. This catches silent MinIO retrieval failures and empty PDF extractions.

4. **PDF extraction fallback.** If PyMuPDF extraction produces >5% garbled characters, retry with `pdfplumber` as a secondary extractor. If both fail, mark as `analysis_status: 'extraction_failed'`.

All quality gate failures produce structured `analysis_status` values rather than silent pass-through. These are surfaced in the report's "Skipped Leads" appendix.

**Extended `analysis_status` values** (additions to original spec's `pending`, `completed`, `no_source_material`, `failed`):

| Status | Meaning | Report handling |
|--------|---------|----------------|
| `pending` | Not yet analyzed | Not in report |
| `completed` | Analysis succeeded | Main report body |
| `not_actionable` | Pass 1 screening found no constitutional issues | Excluded entirely |
| `non_english` | Document not in English | Skipped appendix |
| `extraction_failed` | Text extraction produced garbled/unreadable output | Skipped appendix |
| `no_content` | Extracted text was empty or minimal | Skipped appendix |
| `no_source_material` | Neither MinIO nor source URL produced content | Skipped appendix |
| `failed` | LLM or processing error | Skipped appendix |

---

### 1.4 MinIO Retrieval and Source URL Path

**Source URL is the primary reference.** Every policy lead must carry the original policy page URL from the university portal. This is set by the university policy connector during ingestion and stored in event metadata. The report always renders this URL as the clickable source link.

**MinIO is the backup for text extraction.** When the deep analyzer needs the document text:
1. Try MinIO retrieval first (archived copy, guaranteed stable).
2. If MinIO retrieval fails (missing URI, network error), fall back to fetching from the source URL directly.
3. If both fail, mark as `analysis_status: 'no_source_material'`.

**Implementation note:** The deep analysis spec says `minio_uri` is in `event.raw_data`. The university policy connector may store it in `event.metadata_` instead. The implementation phase must trace and fix this path to ensure consistent retrieval. Regardless of where `minio_uri` lives, the source URL must also be reliably extracted and passed through to the lead's `citations` JSONB.

---

### 1.5 Citations JSONB Population

The `citations` JSONB on leads (defined in the original 2026-03-27 spec) must be populated during deep analysis. Currently it is empty.

**After Pass 2 completes for all provisions:**

```json
{
  "source_citations": [
    {
      "ref_id": 1,
      "type": "policy_document",
      "title": "{document title}",
      "url": "{source_url}",
      "section": "{section_reference from provision}",
      "accessed_at": "{ISO datetime}",
      "archived_artifact_id": "{minio_uri}"
    }
  ],
  "legal_citations": [
    {
      "ref_id": 2,
      "type": "case_law",
      "case_name": "{case_name}",
      "citation": "{citation}",
      "courtlistener_url": "{verified URL or null}",
      "verified": true,
      "relevance": "{one-line from CourtListener holding or precedent map}"
    }
  ]
}
```

Each `sources_cited` entry from the LLM output is resolved against these structured citations. The report template renders them as numbered footnotes with clickable links.

---

### 1.6 Severity Rollup

**Lead severity = max severity across all provisions from Pass 2 analysis.**

A lead with provisions rated `[info, high, medium]` gets lead-level severity `high`. No LLM call needed — simple max over the enum ordering: `info < low < medium < high < critical`.

For incident leads, severity comes from the incident analysis output directly (corroboration strength maps to severity: strong=high, moderate=medium, weak=low, unverified=info).

---

### 1.7 Report Template Fixes

**Confidence bar.** The fill div must set `width` from the confidence value. The confidence is stored as 0.0-1.0 on the lead model; the template must multiply by 100 for the CSS percentage. Ensure the fill div has a visible background color and height.

**Lead titles.** Use `lead_title` from Pass 1 screening output instead of raw event title.

**Source field.** Add a "Source" line to every lead section with a clickable hyperlink to the policy URL.

**Relevant Precedent subsection.** After the provisions list, render CourtListener-verified cases with citation and one-line relevance note.

**Skipped Leads appendix.** New section at the end of the report listing leads that were attempted but could not be analyzed, grouped by failure reason:
- `extraction_failed` — garbled or unreadable document
- `non_english` — document not in English
- `no_content` — empty document or retrieval failure
- `no_source_material` — neither MinIO nor source URL produced content

Each entry shows: institution, document title, source URL (so the attorney can investigate manually), and failure reason.

**Non-actionable filtering.** Leads where Pass 1 screening returns `relevant == false` and no flagged sections are excluded from the main report body. They do not appear at all (not even in the skipped appendix — they were successfully analyzed and found to be irrelevant).

---

### 1.8 Source Configuration Changes

**Remove:**
- `rss_fire` — FIRE is a competitor; their reporting is stale by the time it reaches the platform.
- FIRE handles from xAI x_search trusted handles lists across all jurisdiction queries.

**Retain unchanged:**
- All Texas sources (`x_cal_texas`, `univ_ut`, `univ_tamu`) — remain active, no expansion.
- xAI x_search for CA, MN, DC.
- RSS: Volokh Conspiracy, Courthouse News Service, Higher Ed Dive.
- University policy scraping: UC System, CSU (CA), University of Minnesota (MN), University of the District of Columbia (DC).

---

## Phase 2: New Sources

### 2.1 State Legislature Bill Tracker Connector

**New connector type:** `legislature_tracker`
**New file:** `src/osint_core/connectors/legislature_tracker.py`
**Registration:** `legislature_tracker` in connector registry.

Monitors state legislature websites for bills related to university authority over speech, religion, due process, and parental rights.

**Sources:**
- **CA:** California Legislative Information (leginfo.legislature.ca.gov) — bill search with education/university/speech/religion keywords, track status changes
- **MN:** Minnesota Revisor (revisor.mn.gov) — bill search, committee hearing tracking
- **DC:** DC Council (dccouncil.gov/legislation) — legislation search

**Output:** One `RawItem` per new or changed bill, with:
- Bill number, title, summary
- Full bill text URL
- Status (introduced, committee, passed, signed, vetoed)
- Sponsors
- Committee assignment
- Last action date

**Schedule:** Daily check (bills change less frequently than policies). Configured via plan YAML source entries.

**Content-hash diffing:** Same pattern as university policy connector — track bill text hash to detect amendments and status changes. Only emit new RawItem when content or status changes.

**Lead integration:** Bills create `policy`-type leads (they represent potential or actual policy changes). The deep analyzer's Pass 1 screening works on bill text the same way it works on policy documents.

---

### 2.2 OCR Complaint Database Connector

**New connector type:** `ocr_complaints`
**New file:** `src/osint_core/connectors/ocr_complaints.py`
**Registration:** `ocr_complaints` in connector registry.

Monitors the Department of Education Office for Civil Rights case resolution database for new complaint resolutions against universities in target jurisdictions.

**Output:** One `RawItem` per new resolution, with:
- Institution name
- Complaint type (Title IX, Title VI, Section 504, etc.)
- Resolution type (voluntary resolution, compliance review finding, etc.)
- Resolution date
- Resolution letter URL (if available)
- Case number

**Schedule:** Weekly check (OCR resolutions are published infrequently).

**Lead integration:** OCR resolutions create high-confidence leads because they represent a federal finding of a violation. These should receive a confidence boost in the lead matcher (new factor: `government_finding_bonus`).

---

### 2.3 University Policy Scraping Expansion

Verify that existing MN and DC scrapers are functional and returning content. The connector config already includes University of Minnesota and University of the District of Columbia, but the first production report only contained UC System policies (CA). Investigate whether MN/DC sources are failing silently.

---

### 2.4 FIRE Spotlight Enrichment (Exploratory)

FIRE's Spotlight database rates university speech policies on a public, structured scale. This is distinct from their editorial content (which we're removing as a source).

**Usage:** Enrichment, not collection. During deep analysis of a university policy, check if FIRE Spotlight has a rating for that institution's speech climate. Include the rating as context in the Groq prompt if available.

**Implementation:** TBD — requires evaluating FIRE Spotlight's data access method (API, scraping, or static dataset). Defer detailed design to implementation phase.

---

## New and Modified Components

### New Components

| Component | Type | Path | Phase |
|-----------|------|------|-------|
| Legislature tracker connector | Connector | `src/osint_core/connectors/legislature_tracker.py` | 2 |
| OCR complaints connector | Connector | `src/osint_core/connectors/ocr_complaints.py` | 2 |
| Language detector utility | Utility | `src/osint_core/services/language_detect.py` | 1 |

### Modified Components

| Component | Change | Phase |
|-----------|--------|-------|
| `services/deep_analyzer.py` | Two-pass architecture, enriched prompts, quality gates, citations population | 1 |
| `services/document_extractor.py` | PDF fallback (pdfplumber), encoding validation, empty content check | 1 |
| `services/prospecting_report.py` | Source links, precedent subsection, skipped leads appendix, non-actionable filtering, severity rollup | 1 |
| `templates/prospecting_report.html` | Confidence bar fix, source field, precedent section, skipped appendix, clean titles | 1 |
| `services/lead_matcher.py` | Severity rollup from provisions, government_finding_bonus (Phase 2) | 1, 2 |
| `models/lead.py` | No schema changes — `deep_analysis` JSONB and `analysis_status` already exist | — |
| `plans/cal-prospecting.yaml` | Remove FIRE sources/handles, add legislature and OCR sources (Phase 2) | 1, 2 |
| `connectors/registry.py` | Register `legislature_tracker` and `ocr_complaints` | 2 |
| `workers/deep_analysis.py` | Wire two-pass flow, quality gates before analysis | 1 |

---

## Cost and Performance Impact

**Pass 1 screening:** ~5-20k tokens input, ~500 tokens output per document. Cost: ~$0.001 per policy.

**Pass 2 provision analysis:** ~2-5k tokens input per section, ~500 tokens output. Typically 2-6 sections flagged per relevant document. Cost: ~$0.001-0.003 per document.

**Net effect vs. current:** Similar or lower cost. Current approach sends every chunk (often 5-10 per document) for full analysis. Two-pass sends one screening call + targeted calls only for relevant sections. Documents that are irrelevant (employment policies, gift policies) cost only the Pass 1 screening call instead of full chunk-by-chunk analysis.

**Wall-clock time:** Pass 1 ~2-5s, Pass 2 ~1-2s per section (parallelizable). Total: ~5-15s per document vs. current ~10-30s for heavily chunked documents. Net improvement for relevant documents, significant improvement for irrelevant ones (screened out in ~3s).

**New connectors:** Legislature tracker and OCR complaints add minimal load — low-frequency checks with small response payloads.
