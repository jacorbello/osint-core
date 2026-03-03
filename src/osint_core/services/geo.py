"""Geographic lookup service for mapping countries, ISO codes, and regions.

Data is loaded lazily from a static JSON file on first access and cached
in module-level globals for the lifetime of the process.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

# Module-level caches — populated on first call to _load_data()
_by_iso3: dict[str, dict[str, Any]] | None = None
_by_name: dict[str, dict[str, Any]] | None = None


def _load_data() -> None:
    """Load geo_lookup.json and build lookup indices (called once)."""
    global _by_iso3, _by_name  # noqa: PLW0603

    data_file = resources.files("osint_core.data").joinpath("geo_lookup.json")
    raw: dict[str, dict[str, Any]] = json.loads(data_file.read_text(encoding="utf-8"))

    _by_iso3 = {code.upper(): entry for code, entry in raw.items()}
    _by_name = {entry["name"].lower(): entry for entry in raw.values()}


def _ensure_loaded() -> None:
    """Ensure the data has been loaded into memory."""
    if _by_iso3 is None:
        _load_data()


def lookup_country(iso3: str) -> dict[str, Any] | None:
    """Look up a country by its ISO-3166-1 alpha-3 code.

    Args:
        iso3: Three-letter country code (case-insensitive).

    Returns:
        Country dict or ``None`` if not found.
    """
    _ensure_loaded()
    assert _by_iso3 is not None
    return _by_iso3.get(iso3.upper())


def lookup_gpe(name: str) -> dict[str, Any] | None:
    """Look up a country by its common name.

    Performs an exact match first, then falls back to a substring/partial
    match against all country names.

    Args:
        name: Country name (case-insensitive).

    Returns:
        Country dict or ``None`` if not found.
    """
    _ensure_loaded()
    assert _by_name is not None

    key = name.lower()

    # Exact match
    if key in _by_name:
        return _by_name[key]

    # Partial / substring match — return the first entry whose name
    # contains the query string (or vice-versa).
    for entry_name, entry in _by_name.items():
        if key in entry_name or entry_name in key:
            return entry

    return None


def get_region(iso3: str) -> str | None:
    """Return the geographic region for a given ISO3 code.

    Args:
        iso3: Three-letter country code (case-insensitive).

    Returns:
        Region string or ``None`` if the code is unknown.
    """
    entry = lookup_country(iso3)
    if entry is None:
        return None
    result: str = entry["region"]
    return result
