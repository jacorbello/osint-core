# Plan Templates

Pre-built OSINT collection plan templates for common use cases. Each template
is a valid v2 plan YAML that can be loaded directly via the plan sync endpoint
or customized for your environment.

## Available Templates

| Template | File | Description |
|----------|------|-------------|
| Cyber Threat Intel | `cyber-threat-intel.yaml` | Vulnerability feeds, malware IOCs, and security news |
| Physical Security | `physical-security.yaml` | Conflict events, severe weather, natural disasters, local news |
| Geopolitical Monitoring | `geopolitical-monitoring.yaml` | International affairs, armed conflicts, diplomatic developments |
| Brand / Reputation | `brand-reputation.yaml` | Media mentions, data breach alerts, brand sentiment tracking |

## Cyber Threat Intel

Monitors vulnerability disclosures and malware indicators across authoritative
sources. Best suited for security operations teams needing continuous awareness
of emerging threats.

**Sources:** CISA KEV, NVD, ThreatFox, URLhaus, OTX, MalwareBazaar, The Hacker
News RSS, BleepingComputer RSS

**Schedule:** Feeds polled every 1-4 hours depending on source update frequency.

**API keys required:** `OSINT_OTX_API_KEY` (AlienVault OTX)

## Physical Security

Tracks physical security events including armed conflict, civil unrest, severe
weather, and breaking local news. Designed for security teams responsible for
facility protection and personnel safety.

**Sources:** GDELT (event search), ACLED (conflict data), NWS Alerts (weather),
Google News RSS, Reuters RSS

**Schedule:** GDELT and NWS polled every 10-15 minutes; other sources hourly to
every 4 hours.

**API keys required:** `OSINT_ACLED_API_KEY`, `OSINT_ACLED_EMAIL` (ACLED)

## Geopolitical Monitoring

Monitors international developments, diplomatic activity, and humanitarian
crises from a mix of event data APIs and international news outlets. Useful for
analysts tracking regional stability and policy impacts.

**Sources:** GDELT (geopolitical search), ACLED, ReliefWeb, BBC World RSS,
Al Jazeera RSS, Foreign Affairs RSS, Crisis Group RSS

**Schedule:** GDELT every 15 minutes; APIs every 4 hours; RSS every 2-6 hours.

**API keys required:** `OSINT_ACLED_API_KEY`, `OSINT_ACLED_EMAIL` (ACLED)

## Brand / Reputation

Tracks media mentions, data breach disclosures, and public sentiment around a
brand or product. Requires customization of the GDELT query and keywords to
match your specific brand and product names.

**Sources:** GDELT (brand search), Google News RSS, TechCrunch RSS, The Verge
RSS, Ars Technica RSS

**Schedule:** GDELT every 30 minutes; RSS feeds every 1-2 hours.

**API keys required:** None (all public feeds)

## How to Use a Template

1. **Copy** the template YAML into your `plans/` directory.
2. **Rename** the `plan_id` field to something unique (e.g., change
   `tpl-cyber-threat-intel` to `acme-cyber-threat-intel`).
3. **Customize** keywords, sources, scoring weights, and notification channels
   to match your requirements.
4. **Set environment variables** for any required API keys (listed above).
5. **Load** the plan via the sync endpoint:
   ```
   POST /api/v1/plans:sync-from-disk
   ```
   Or submit it directly:
   ```
   POST /api/v1/plans
   Content-Type: application/json
   {"yaml": "<your plan YAML>", "activate": true}
   ```

## Customization Guide

### Adjusting Sources

- Add or remove sources by editing the `sources` list. Each source needs a
  unique `id`, a valid `type` from the schema, a `url`, and a `schedule_cron`.
- Available source types: `rss`, `cisa_kev`, `nvd_json_feed`, `osv_api`,
  `urlhaus_api`, `threatfox_api`, `otx_api`, `abusech_malwarebazaar`,
  `abusech_feodotracker`, `gdelt_api`, `reliefweb_api`, `acled_api`,
  `nws_alerts`, `shodan_api`, `github_releases`, `http_json`, `http_html`,
  `http_pdf`, `sitemap`.

### Tuning Scoring

- `recency_half_life_hours` controls how quickly old items lose relevance.
  Lower values (6-12) suit fast-moving situations; higher values (48-168) suit
  slower intelligence cycles.
- `source_reputation` weights range from 0.0 to 10.0. Higher values give more
  influence to that source in the final score.
- `ioc_match_boost` amplifies items that match known indicators of compromise.
- `severity_promotions` can automatically escalate items matching specific
  conditions.

### Notification Channels

Each route needs at least one channel. Supported types:
- `gotify` — requires `application` and `priority` (0-10)
- `slack` — requires `url` (webhook URL)
- `email` — requires `to` (recipient address)
- `webhook` — requires `url`

### Keywords

The `keywords` list drives relevance scoring. Items matching more keywords
receive higher scores. Keep the list focused (10-20 terms) to reduce noise.

### Parent Plans

To group templates under a master plan, add a `parent_plan_id` field pointing
to your master plan and remove any notification settings that the master plan
already provides via its `defaults` section.
