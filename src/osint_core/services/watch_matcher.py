"""Watch matching service — determines if events match active watches."""

from typing import Any

SEVERITY_ORDER = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def matches_watch(event: dict[str, Any], watch: dict[str, Any]) -> bool:
    """Check if an event matches a watch's criteria.

    An event matches if:
      1. At least one geographic or keyword criterion matches, AND
      2. The event's severity meets or exceeds the watch's threshold.

    Args:
        event: Dict with keys: country_code, latitude, longitude, title, summary, severity
        watch: Dict with keys: country_codes, bounding_box, keywords, severity_threshold

    Returns:
        True if the event matches the watch.
    """
    # Check severity threshold first
    event_severity = SEVERITY_ORDER.get(event.get("severity", "info"), 0)
    threshold = SEVERITY_ORDER.get(watch.get("severity_threshold", "low"), 1)
    if event_severity < threshold:
        return False

    # Check geographic / keyword criteria (at least one must match)
    criteria_matched = False

    # Country code match
    watch_codes = watch.get("country_codes")
    if watch_codes and event.get("country_code"):
        if event["country_code"] in watch_codes:
            criteria_matched = True

    # Bounding box match
    bbox = watch.get("bounding_box")
    if bbox and event.get("latitude") is not None and event.get("longitude") is not None:
        lat, lon = event["latitude"], event["longitude"]
        if (
            bbox["south"] <= lat <= bbox["north"]
            and bbox["west"] <= lon <= bbox["east"]
        ):
            criteria_matched = True

    # Keyword match
    watch_keywords = watch.get("keywords")
    if watch_keywords:
        text = f"{event.get('title', '')} {event.get('summary', '')}".lower()
        for keyword in watch_keywords:
            if keyword.lower() in text:
                criteria_matched = True
                break

    return criteria_matched
