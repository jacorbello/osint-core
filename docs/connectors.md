# Connectors Reference

Connectors are the data ingestion layer of osint-core. Each connector fetches data from a single external source (API, feed, or website), normalizes it into `RawItem` objects, and provides a deduplication key for each item. The platform currently ships 19 connectors covering cyber threat intelligence, geopolitical events, social media, weather alerts, humanitarian data, and policy monitoring.

---

## Base Interface

All connectors extend `BaseConnector` and implement two abstract methods. The base classes live in `src/osint_core/connectors/base.py`.

### BaseConnector

```python
class BaseConnector(ABC):
    def __init__(self, config: SourceConfig):
        self.config = config

    @abstractmethod
    async def fetch(self) -> list[RawItem]:
        ...

    @abstractmethod
    def dedupe_key(self, item: RawItem) -> str:
        ...
```

- **`fetch()`** -- Async method that retrieves data from the external source and returns a list of `RawItem` objects. Responsible for HTTP calls, pagination, rate-limit retries, and response parsing.
- **`dedupe_key(item)`** -- Returns a stable string key used to deduplicate items across fetches. Typically a prefix (e.g., `nvd:`, `gdelt:`) combined with a hash or unique ID.

### SourceConfig

```python
@dataclass
class SourceConfig:
    id: str                              # Unique source identifier within a plan
    type: str                            # Registry key (e.g., "cisa_kev", "rss")
    url: str                             # Base URL for the data source
    weight: float                        # Scoring weight
    extra: dict[str, Any] = field(...)   # Connector-specific parameters
```

The `extra` dict carries all connector-specific configuration: API keys, query strings, lookback windows, max items, keywords, and so on. Plan YAML files populate this via the `params` block.

### RawItem

```python
@dataclass
class RawItem:
    title: str
    url: str
    raw_data: dict[str, Any]
    summary: str = ""
    occurred_at: datetime | None = None
    severity: str | None = None
    indicators: list[dict[str, Any]] = field(...)
    latitude: float | None = None
    longitude: float | None = None
    country_code: str | None = None
    region: str | None = None
    source_category: str | None = None
    actors: list[dict[str, Any]] = field(...)
    event_type: str | None = None
    event_subtype: str | None = None
    fatalities: int | None = None
```

Key fields:
- **`indicators`** -- Structured IOCs (CVEs, IPs, domains, hashes, URLs, packages).
- **`source_category`** -- Broad classification: `"cyber"`, `"geopolitical"`, `"social_media"`, `"weather"`, `"humanitarian"`.
- **`country_code`** -- ISO 3166-1 alpha-3 (e.g., `"USA"`, `"UKR"`). Connectors normalize from ISO-2 where needed.
- **`actors`** / **`fatalities`** -- Used primarily by conflict-oriented connectors (ACLED).

---

## Registry

The `ConnectorRegistry` class in `src/osint_core/connectors/registry.py` maps string `source_type` keys to connector classes.

```python
class ConnectorRegistry:
    def register(self, source_type: str, cls: type[BaseConnector]) -> None
    def get(self, source_type: str, config: SourceConfig) -> BaseConnector
    def has(self, source_type: str) -> bool
```

All 18 connectors are registered at import time in `src/osint_core/connectors/__init__.py`. The singleton `registry` is the global instance used by the ingest pipeline.

### Adding a New Connector

1. Create a new file in `src/osint_core/connectors/` implementing `BaseConnector`.
2. Import the class in `__init__.py`.
3. Call `registry.register("your_source_type", YourConnectorClass)`.
4. Add the class to `__all__`.
5. Reference the `source_type` key in plan YAML files under `sources[].type`.

---

## Connector Catalog

### Summary Table

| source_type | Class | Data Source | Required Config |
|---|---|---|---|
| `abusech_feodotracker` | `FeodoTrackerConnector` | abuse.ch Feodo Tracker | None (public API) |
| `abusech_malwarebazaar` | `MalwareBazaarConnector` | abuse.ch MalwareBazaar | None (public API) |
| `acled_api` | `AcledConnector` | ACLED conflict data | `OSINT_ACLED_EMAIL`, `OSINT_ACLED_PASSWORD` |
| `cisa_kev` | `CisaKevConnector` | CISA KEV catalog | None (public JSON) |
| `gdelt_api` | `GdeltConnector` | GDELT DOC 2.0 API | None (public API) |
| `nvd_json_feed` | `NvdConnector` | NVD API 2.0 | None (public API) |
| `nws_alerts` | `NwsConnector` | NWS alerts API | None (public API) |
| `osv_api` | `OsvConnector` | OSV vulnerability API | None (public API) |
| `otx_api` | `OtxConnector` | AlienVault OTX | `OSINT_OTX_API_KEY` (via params) |
| `pastebin` | `PasteSiteConnector` | Paste site search API | None (public API) |
| `reddit` | `RedditConnector` | Reddit JSON API | None (public API) |
| `reliefweb_api` | `ReliefWebConnector` | ReliefWeb API v2 | None (public API) |
| `rss` | `RssConnector` | Any RSS/Atom feed | None |
| `shodan_api` | `ShodanConnector` | Shodan search API | `OSINT_SHODAN_API_KEY` or params `api_key` |
| `telegram` | `TelegramConnector` | Telegram Bot API | `OSINT_TELEGRAM_BOT_TOKEN` or params `bot_token` |
| `threatfox_api` | `ThreatFoxConnector` | abuse.ch ThreatFox | None (public API) |
| `university_policy` | `UniversityPolicyConnector` | University policy portals | Redis (optional), MinIO (for archival) |
| `urlhaus_api` | `UrlhausConnector` | abuse.ch URLhaus | None (public API) |
| `xai_x_search` | `XaiXSearchConnector` | xAI Grok x_search (X/Twitter) | `OSINT_XAI_API_KEY` (via params) |

---

### abusech_feodotracker

**File:** `src/osint_core/connectors/abusech.py`
**Class:** `FeodoTrackerConnector`
**Data Source:** [Feodo Tracker](https://feodotracker.abuse.ch) -- C2 server blocklist

**Fetch behavior:**
- GET request to the configured URL (typically the recent IP blocklist JSON endpoint).
- Parses the JSON array of C2 server entries.
- Caps results at `max_items` (default 100).

**Config params (`extra`):**
- `max_items` (int, default 100) -- Maximum entries to return.

**Indicators:** IP addresses of C2 servers.
**Dedupe key:** `feodo:{sha256(ip)[:16]}`

---

### abusech_malwarebazaar

**File:** `src/osint_core/connectors/abusech.py`
**Class:** `MalwareBazaarConnector`
**Data Source:** [MalwareBazaar](https://bazaar.abuse.ch) -- Malware sample repository

**Fetch behavior:**
- POST request with `query=get_recent&selector=time`.
- Returns recent malware samples with file type, signature, and hash data.
- Caps results at `max_items` (default 100).

**Config params (`extra`):**
- `max_items` (int, default 100) -- Maximum samples to return.

**Indicators:** SHA-256 file hashes.
**Dedupe key:** `mb:{sha256[:16]}`

---

### acled_api

**File:** `src/osint_core/connectors/acled.py`
**Class:** `AcledConnector`
**Data Source:** [ACLED](https://acleddata.com) -- Armed Conflict Location & Event Data

**Fetch behavior:**
- Authenticates via OAuth password grant to obtain a Bearer token (cached at module level per email).
- GET request to the ACLED read API with country and limit params.
- Rate-limit retry: up to 3 attempts on 429/503, honoring `Retry-After` header (capped at 60s).
- Returns conflict event records with geolocation, actors, fatalities, and event type.

**Config params (`extra`):**
- `email` (str, required) -- ACLED account email (`${OSINT_ACLED_EMAIL}`).
- `password` (str, required) -- ACLED account password (`${OSINT_ACLED_PASSWORD}`).
- `country` (str, optional) -- Filter by country name.
- `max_items` (int, default 100) -- Maximum events to return.

**source_category:** `"geopolitical"`
**Dedupe key:** `acled:{sha256(event_id_cnty)[:16]}`

---

### cisa_kev

**File:** `src/osint_core/connectors/cisa_kev.py`
**Class:** `CisaKevConnector`
**Data Source:** [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) -- Known Exploited Vulnerabilities

**Fetch behavior:**
- GET request to the CISA KEV JSON feed.
- Parses the full `vulnerabilities` array (no pagination or lookback).
- Returns all known exploited vulnerabilities with CVE ID, vendor, product, and description.

**Config params (`extra`):** None required.

**Indicators:** CVE identifiers.
**Dedupe key:** `cisa_kev:{cveID}`

---

### gdelt_api

**File:** `src/osint_core/connectors/gdelt.py`
**Class:** `GdeltConnector`
**Data Source:** [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) -- Global media event monitoring

**Fetch behavior:**
- GET request to the GDELT DOC 2.0 API with a constructed query.
- Supports `geo_terms` (geographic AND filter), `preferred_languages` (source language filter), and `lookback_hours` (converted to timespan minutes).
- Rate-limit retry: up to 3 attempts on 429/503.
- Optional `max_per_domain` cap to prevent source domination.
- Filters out articles with empty titles.

**Config params (`extra`):**
- `query` (str) -- Base search query with boolean operators.
- `geo_terms` (str, optional) -- Geographic filter terms (OR-joined, AND-ed with query).
- `preferred_languages` (list[str], optional) -- Language codes for `sourcelang:` filter.
- `mode` (str, default `"ArtList"`) -- GDELT query mode.
- `maxrecords` (str/int, default `"100"`) -- Max results from GDELT.
- `lookback_hours` (int, default 4) -- How far back to search (converted to `timespan`).
- `timespan` (str, optional) -- Override timespan directly (e.g., `"15min"`).
- `max_per_domain` (int, optional) -- Cap articles per domain.
- `max_items` (int, default 100) -- Final cap on returned items.

**source_category:** `"geopolitical"`
**Dedupe key:** `gdelt:{sha256(url)[:16]}`

---

### nvd_json_feed

**File:** `src/osint_core/connectors/nvd.py`
**Class:** `NvdConnector`
**Data Source:** [NVD API 2.0](https://nvd.nist.gov/developers/vulnerabilities) -- National Vulnerability Database

**Fetch behavior:**
- GET requests with pagination (2000 results per page).
- Supports `lookback_hours` to filter by `lastModStartDate`/`lastModEndDate`.
- Pages up to `max_pages` (default 5), logging a warning if results are truncated.
- Passes through any extra params not in the connector-only key set.

**Config params (`extra`):**
- `lookback_hours` (int, optional) -- Only fetch CVEs modified within this window.
- `max_pages` (int, default 5) -- Maximum pages to fetch.
- `max_items` (int, optional) -- Not used internally; extra API params are passed through.

**Indicators:** CVE identifiers. Extracts CVSS severity from v3.1/v3.0/v2 metrics.
**Dedupe key:** `nvd:{cve_id}`

---

### nws_alerts

**File:** `src/osint_core/connectors/nws.py`
**Class:** `NwsConnector`
**Data Source:** [NWS Alerts API](https://api.weather.gov) -- National Weather Service active alerts

**Fetch behavior:**
- GET request to the NWS alerts endpoint with GeoJSON accept header.
- Sets `User-Agent` to `(osint-core, admin@corbello.io)` as required by NWS API policy.
- Optional `zone` filter for geographic targeting.
- Maps NWS severity levels (Extreme/Severe/Moderate/Minor/Unknown) to platform levels (critical/high/medium/low/info).

**Config params (`extra`):**
- `zone` (str, optional) -- NWS zone code (e.g., `TXC453` for Travis County).
- `max_items` (int, default 100) -- Maximum alerts to return.

**source_category:** `"weather"`
**country_code:** Always `"USA"`.
**Dedupe key:** `nws:{sha256(alert_id)[:16]}`

---

### osv_api

**File:** `src/osint_core/connectors/osv.py`
**Class:** `OsvConnector`
**Data Source:** [OSV API](https://osv.dev) -- Open Source Vulnerability database

**Fetch behavior:**
- POST request with a JSON body specifying the package ecosystem.
- Returns vulnerability records with aliases (CVE cross-references) and affected packages.

**Config params (`extra`):**
- `ecosystem` (str, default `""`) -- Package ecosystem to query (e.g., `"PyPI"`, `"npm"`).

**Indicators:** CVE aliases and affected package names with ecosystem metadata.
**Dedupe key:** `osv:{vuln_id}`

---

### otx_api

**File:** `src/osint_core/connectors/otx.py`
**Class:** `OtxConnector`
**Data Source:** [AlienVault OTX](https://otx.alienvault.com) -- Open Threat Exchange pulse feed

**Fetch behavior:**
- GET request with `X-OTX-API-KEY` header.
- Returns threat intelligence pulses with associated indicators.
- Caps results at `max_items` (default 100).

**Config params (`extra`):**
- `api_key` (str, required) -- OTX API key (`${OSINT_OTX_API_KEY}`).
- `max_items` (int, default 100) -- Maximum pulses to return.

**source_category:** `"cyber"`
**Dedupe key:** `otx:{sha256(pulse_id)[:16]}`

---

### pastebin

**File:** `src/osint_core/connectors/pastebin.py`
**Class:** `PasteSiteConnector`
**Data Source:** [psbdmp.ws](https://psbdmp.ws) (default) -- Paste site search API

**Fetch behavior:**
- Iterates over configured `keywords`, issuing a GET request per keyword to the search API.
- Deduplicates results by paste ID across keywords.
- Filters by `lookback_hours` window (default 24 hours).
- Runs indicator extraction (`extract_indicators`) on paste content to surface IPs, domains, hashes, CVEs, and URLs.
- Stores only bounded content excerpts in `raw_data` to avoid persisting sensitive credentials.

**Config params (`extra`):**
- `keywords` (list[str], required) -- Search terms. Returns empty if not set.
- `max_items` (int, default 100) -- Maximum total pastes to return.
- `lookback_hours` (int, default 24) -- Filter pastes older than this window.
- `timeout` (int, default 30) -- HTTP timeout in seconds.

**source_category:** `"cyber"`
**Dedupe key:** `pastebin:{sha256(paste_id)[:16]}`

---

### reddit

**File:** `src/osint_core/connectors/reddit.py`
**Class:** `RedditConnector`
**Data Source:** [Reddit JSON API](https://www.reddit.com) -- Public subreddit posts

**Fetch behavior:**
- Fetches posts from one or more subreddits via Reddit's public `.json` endpoint.
- Validates subreddit names against `[A-Za-z0-9_]` regex to prevent path injection.
- Supports sort modes: `hot`, `new`, `top`, `rising`.
- Rate-limit retry: up to 3 attempts on 429.
- Optional `keyword_filter` for case-insensitive post filtering.
- Excludes volatile fields (score, num_comments) from `raw_data` for stable deduplication.

**Config params (`extra`):**
- `subreddits` (list[str], required) -- Subreddit names without `r/` prefix.
- `sort` (str, default `"hot"`) -- Sort order.
- `limit` (int, default 25, max 100) -- Max posts per subreddit.
- `keyword_filter` (list[str], optional) -- Only include posts matching any keyword.

**source_category:** `"social_media"`
**Dedupe key:** `reddit:{reddit_id}`

---

### reliefweb_api

**File:** `src/osint_core/connectors/reliefweb.py`
**Class:** `ReliefWebConnector`
**Data Source:** [ReliefWeb API v2](https://api.reliefweb.int) -- UN OCHA humanitarian reports

**Fetch behavior:**
- POST request with a structured JSON body requesting specific fields.
- Sorts by `date.created:desc`, returns up to 50 reports per fetch.
- Optional country filter by ISO-3 code.

**Config params (`extra`):**
- `appname` (str, default `"osint-core"`) -- Application name for API tracking.
- `countries` (str/list, optional) -- ISO-3 country codes to filter by.

**source_category:** `"humanitarian"`
**Dedupe key:** `reliefweb:{report_id}`

---

### rss

**File:** `src/osint_core/connectors/rss.py`
**Class:** `RssConnector`
**Data Source:** Any RSS or Atom feed

**Fetch behavior:**
- GET request to the feed URL with retry logic (up to 3 attempts for 429, 5xx errors, and transport errors).
- Uses exponential backoff with `Retry-After` header support.
- Parses the feed via `feedparser`.
- Extracts date from `published_parsed`, `updated_parsed`, or raw date string fallback.

**Config params (`extra`):** None specific. The feed URL is set via `config.url`.

**Dedupe key:** `rss:{source_id}:{sha256(link)[:16]}`

---

### shodan_api

**File:** `src/osint_core/connectors/shodan.py`
**Class:** `ShodanConnector`
**Data Source:** [Shodan](https://www.shodan.io) -- Internet-connected device search

**Fetch behavior:**
- GET request to the Shodan search API with a query and API key.
- API key resolved from params `api_key` or global `OSINT_SHODAN_API_KEY` setting.
- Returns host matches with IPs, ports, products, versions, vulnerabilities, and geolocation.
- Normalizes ISO-2 country codes to ISO-3 via `iso2_to_iso3`.

**Config params (`extra`):**
- `api_key` (str, optional) -- Shodan API key. Falls back to `OSINT_SHODAN_API_KEY` env var.
- `query` (str, required) -- Shodan search query (e.g., `"port:22 country:US"`).

**source_category:** `"cyber"`
**Indicators:** IP addresses, CVEs (from `vulns`), domains (from `hostnames`).
**Dedupe key:** `shodan:{sha256(ip:port:timestamp)[:16]}`

---

### telegram

**File:** `src/osint_core/connectors/telegram.py`
**Class:** `TelegramConnector`
**Data Source:** [Telegram Bot API](https://core.telegram.org/bots/api) -- Public channel messages

**Fetch behavior:**
- GET request to `getUpdates` endpoint with `allowed_updates=["channel_post"]`.
- Filters messages by `channel_username` (case-insensitive).
- Supports `lookback_hours` window (default 24) and keyword filtering.
- Tracks `_update_offset` in `config.extra` to avoid re-fetching processed messages.
- Extracts media download URLs (photos, documents, videos, audio, voice, animation).

**Config params (`extra`):**
- `bot_token` (str, optional) -- Telegram bot token. Falls back to `OSINT_TELEGRAM_BOT_TOKEN`.
- `channel_username` (str, required) -- Public channel username (without `@`).
- `keywords` (list[str], optional) -- Filter messages by keyword.
- `lookback_hours` (int, default 24) -- Message age filter.

**Dedupe key:** `telegram:{source_id}:{sha256(chat_id:message_id)[:16]}`

---

### threatfox_api

**File:** `src/osint_core/connectors/threatfox.py`
**Class:** `ThreatFoxConnector`
**Data Source:** [ThreatFox](https://threatfox.abuse.ch) -- abuse.ch IOC database

**Fetch behavior:**
- POST request with `{"query": "get_iocs", "days": 1}`.
- Returns IOCs from the last 24 hours with malware family, threat type, and confidence level.

**Config params (`extra`):** None required.

**Indicators:** IOC type/value pairs (IP, domain, URL, hash, etc.).
**Dedupe key:** `threatfox:{ioc_id}`

---

### university_policy

**File:** `src/osint_core/connectors/university_policy.py`
**Class:** `UniversityPolicyConnector`
**Data Source:** University policy portal websites (configurable)

**Fetch behavior:**
- Scrapes institution policy index pages using configurable CSS selectors.
- Follows redirects with SSRF validation (domain allowlist, private IP rejection).
- Downloads linked policy documents (HTML and PDF).
- Computes SHA-256 content hashes; only emits `RawItem` for new or changed documents.
- Stores hashes in Redis (with in-memory fallback if Redis is unavailable).
- Archives documents to MinIO (`osint-artifacts` bucket) with `evidentiary` retention class.
- HTTP retry logic: up to 3 attempts for 429/5xx with exponential backoff.
- Validates CSS selectors at init time via `soupsieve`.

**Config params (`extra`):**
- `institutions` (list[dict], optional) -- List of `{name, policy_url, selector}` dicts. Defaults to 6 built-in institutions (UC System, CSU System, UT System, TAMU System, UMN, UDC).
- `allowed_domain_suffixes` (list[str], default `[".edu"]`) -- SSRF allowlist for URL validation.
- `allowed_domains` (list[str], optional) -- Additional exact domains to allow.
- `archive_pdfs` (bool, default `true`) -- Whether to archive PDF documents to MinIO.

**Infrastructure dependencies:** Redis (optional, for hash persistence), MinIO (for document archival).
**Dedupe key:** `university_policy:{source_id}:{sha256(url)[:16]}:{content_hash[:8]}`

---

### urlhaus_api

**File:** `src/osint_core/connectors/urlhaus.py`
**Class:** `UrlhausConnector`
**Data Source:** [URLhaus](https://urlhaus.abuse.ch) -- Malicious URL tracker

**Fetch behavior:**
- POST request with `query=recent&limit=100`.
- Returns recent malicious URLs with host, threat type, and tags.

**Config params (`extra`):** None required.

**Indicators:** Malicious URLs and extracted host domains.
**Dedupe key:** `urlhaus:{sha256(url)[:16]}`

---

### xai_x_search

**File:** `src/osint_core/connectors/xai_x_search.py`
**Class:** `XaiXSearchConnector`
**Data Source:** [xAI Grok API](https://docs.x.ai) with `x_search` tool -- X/Twitter search

**Fetch behavior:**
- POST request to `https://api.x.ai/v1/responses` with a structured prompt and the `x_search` tool definition.
- Builds a multi-search prompt instructing Grok to execute keyword and semantic searches.
- Supports `from_date`/`to_date` based on `lookback_hours`.
- Rate-limit retry: up to 3 attempts on 429 and 5xx.
- Response parsing: primary path attempts JSON array extraction; fallback parses URL citations from response annotations.
- Includes truncated JSON recovery for partial API responses.
- 180-second HTTP timeout (longer due to LLM processing).

**Config params (`extra`):**
- `api_key` (str, required) -- xAI API key (`${OSINT_XAI_API_KEY}`).
- `searches` (list[str], required) -- Search queries to execute.
- `mission` (str, optional) -- Context for Grok about what to look for.
- `geo_terms` (str, optional) -- Geographic focus area.
- `model` (str, default `"grok-4.20-reasoning"`) -- Grok model to use.
- `lookback_hours` (int, default 24) -- Search window.
- `max_results` (int, default 50) -- Cap on returned items.
- `allowed_x_handles` (list[str], optional) -- Only search these handles (max 10).
- `excluded_x_handles` (list[str], optional) -- Exclude these handles (max 10).
- `enable_image_understanding` (bool, optional) -- Analyze images in posts.
- `enable_video_understanding` (bool, optional) -- Analyze videos in posts.

**source_category:** `"social_media"`
**Dedupe key:** `xai:{status_id}` (extracted from tweet URL) or `xai:{sha256(url)[:16]}`

---

## Plan Usage

The following table shows which `source_type` keys each plan YAML references.

| source_type | austin-terror-threat | austin-terror-watch | cal-prospecting | cortech-osint-master | cyber-threat-intel | example | humanitarian-intel | military-intel |
|---|---|---|---|---|---|---|---|---|
| `acled_api` | x | x | | | | | x | |
| `abusech_feodotracker` | | | | | x | | | |
| `abusech_malwarebazaar` | | | | | x | | | |
| `cisa_kev` | | | | | x | x | | |
| `gdelt_api` | x | x | | | | | | x |
| `nvd_json_feed` | | | | | x | x | | |
| `nws_alerts` | x | x | | | | | | |
| `osv_api` | | | | | x | x | | |
| `otx_api` | | | | | x | | | |
| `pastebin` | | | | | | | | |
| `reddit` | x | | | | | | | |
| `reliefweb_api` | | | | | | | x | |
| `rss` | x | x | x | | x | x | x | x |
| `shodan_api` | | | | | | | | x |
| `telegram` | | | | | | | | |
| `threatfox_api` | | | | | x | x | | |
| `university_policy` | | | x | | | | | |
| `urlhaus_api` | | | | | x | x | | |
| `xai_x_search` | x | | x | | | | | |

**Notes:**
- The `cortech-osint-master` plan is a master plan that defines global defaults and references child plans; it does not define its own sources.
- The `example` plan (`example.yaml`) uses `plan_id: libertycenter-osint` and is a v1 plan format.
- `pastebin` and `telegram` connectors are registered but not currently referenced by any plan YAML.
