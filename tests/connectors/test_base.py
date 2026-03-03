"""Tests for RawItem geographic and military intel fields."""


from osint_core.connectors.base import RawItem


def _minimal_raw_item(**overrides) -> RawItem:
    """Create a RawItem with only the required fields, plus any overrides."""
    defaults = {
        "title": "Test event",
        "url": "https://example.com/event",
        "raw_data": {"key": "value"},
    }
    return RawItem(**(defaults | overrides))


class TestRawItemGeoFieldsDefaultToNone:
    """New geographic fields must default to None (or empty list for actors)."""

    def test_latitude_defaults_to_none(self):
        item = _minimal_raw_item()
        assert item.latitude is None

    def test_longitude_defaults_to_none(self):
        item = _minimal_raw_item()
        assert item.longitude is None

    def test_country_code_defaults_to_none(self):
        item = _minimal_raw_item()
        assert item.country_code is None

    def test_region_defaults_to_none(self):
        item = _minimal_raw_item()
        assert item.region is None

    def test_source_category_defaults_to_none(self):
        item = _minimal_raw_item()
        assert item.source_category is None

    def test_event_type_defaults_to_none(self):
        item = _minimal_raw_item()
        assert item.event_type is None

    def test_fatalities_defaults_to_none(self):
        item = _minimal_raw_item()
        assert item.fatalities is None

    def test_actors_defaults_to_empty_list(self):
        item = _minimal_raw_item()
        assert item.actors == []


class TestRawItemGeoFieldsCanBeSet:
    """All geographic fields can be populated at construction time."""

    def test_all_geo_fields_populated(self):
        item = _minimal_raw_item(
            latitude=33.749,
            longitude=-84.388,
            country_code="US",
            region="Georgia",
            source_category="conflict",
            event_type="protest",
            fatalities=0,
            actors=[{"name": "Group A", "role": "attacker"}],
        )
        assert item.latitude == 33.749
        assert item.longitude == -84.388
        assert item.country_code == "US"
        assert item.region == "Georgia"
        assert item.source_category == "conflict"
        assert item.event_type == "protest"
        assert item.fatalities == 0
        assert item.actors == [{"name": "Group A", "role": "attacker"}]


class TestRawItemActorsField:
    """The actors field stores a list of dicts describing involved parties."""

    def test_single_actor(self):
        item = _minimal_raw_item(
            actors=[{"name": "APT-29", "country": "RU"}],
        )
        assert len(item.actors) == 1
        assert item.actors[0]["name"] == "APT-29"

    def test_multiple_actors(self):
        actors = [
            {"name": "Group Alpha", "role": "attacker"},
            {"name": "Group Beta", "role": "target"},
        ]
        item = _minimal_raw_item(actors=actors)
        assert len(item.actors) == 2
        assert item.actors[1]["role"] == "target"

    def test_actors_default_not_shared_across_instances(self):
        item_a = _minimal_raw_item()
        item_b = _minimal_raw_item()
        item_a.actors.append({"name": "Mutant"})
        assert item_b.actors == [], "default_factory must prevent shared mutable default"


class TestRawItemFatalitiesField:
    """The fatalities field is an optional int for conflict event data."""

    def test_fatalities_zero(self):
        item = _minimal_raw_item(fatalities=0)
        assert item.fatalities == 0

    def test_fatalities_positive(self):
        item = _minimal_raw_item(fatalities=42)
        assert item.fatalities == 42

    def test_fatalities_none_when_not_applicable(self):
        item = _minimal_raw_item()
        assert item.fatalities is None
