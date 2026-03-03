"""Tests for the watch matching service."""


from osint_core.services.watch_matcher import matches_watch


def test_matches_by_country_code():
    watch = {
        "country_codes": ["UKR", "RUS"],
        "bounding_box": None,
        "keywords": None,
        "severity_threshold": "low",
    }
    event = {
        "country_code": "UKR",
        "latitude": None,
        "longitude": None,
        "title": "Event in Ukraine",
        "summary": "Something happened",
        "severity": "medium",
    }
    assert matches_watch(event, watch) is True


def test_no_match_wrong_country():
    watch = {
        "country_codes": ["UKR", "RUS"],
        "bounding_box": None,
        "keywords": None,
        "severity_threshold": "low",
    }
    event = {
        "country_code": "USA",
        "latitude": None,
        "longitude": None,
        "title": "Event in USA",
        "summary": "Something happened",
        "severity": "medium",
    }
    assert matches_watch(event, watch) is False


def test_matches_by_keyword():
    watch = {
        "country_codes": None,
        "bounding_box": None,
        "keywords": ["NATO", "nuclear"],
        "severity_threshold": "low",
    }
    event = {
        "country_code": None,
        "latitude": None,
        "longitude": None,
        "title": "NATO alliance meeting discusses expansion",
        "summary": "Defense ministers met today",
        "severity": "medium",
    }
    assert matches_watch(event, watch) is True


def test_no_match_keyword_absent():
    watch = {
        "country_codes": None,
        "bounding_box": None,
        "keywords": ["NATO", "nuclear"],
        "severity_threshold": "low",
    }
    event = {
        "country_code": None,
        "latitude": None,
        "longitude": None,
        "title": "Weather forecast for Tuesday",
        "summary": "Rain expected",
        "severity": "medium",
    }
    assert matches_watch(event, watch) is False


def test_matches_by_bounding_box():
    watch = {
        "country_codes": None,
        "bounding_box": {"north": 52.0, "south": 44.0, "east": 40.0, "west": 22.0},
        "keywords": None,
        "severity_threshold": "low",
    }
    event = {
        "country_code": None,
        "latitude": 48.38,
        "longitude": 31.17,
        "title": "Event",
        "summary": "",
        "severity": "medium",
    }
    assert matches_watch(event, watch) is True


def test_no_match_outside_bounding_box():
    watch = {
        "country_codes": None,
        "bounding_box": {"north": 52.0, "south": 44.0, "east": 40.0, "west": 22.0},
        "keywords": None,
        "severity_threshold": "low",
    }
    event = {
        "country_code": None,
        "latitude": 37.0,
        "longitude": -122.0,
        "title": "Event",
        "summary": "",
        "severity": "medium",
    }
    assert matches_watch(event, watch) is False


def test_severity_below_threshold_no_match():
    watch = {
        "country_codes": ["UKR"],
        "bounding_box": None,
        "keywords": None,
        "severity_threshold": "high",
    }
    event = {
        "country_code": "UKR",
        "latitude": None,
        "longitude": None,
        "title": "Minor event",
        "summary": "",
        "severity": "low",
    }
    assert matches_watch(event, watch) is False


def test_no_criteria_no_match():
    watch = {
        "country_codes": None,
        "bounding_box": None,
        "keywords": None,
        "severity_threshold": "low",
    }
    event = {
        "country_code": "UKR",
        "latitude": None,
        "longitude": None,
        "title": "Event",
        "summary": "",
        "severity": "medium",
    }
    assert matches_watch(event, watch) is False
