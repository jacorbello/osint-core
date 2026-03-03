"""Tests for the geographic lookup service."""

from __future__ import annotations

from osint_core.services.geo import get_region, lookup_country, lookup_gpe


class TestLookupCountry:
    """Tests for lookup_country (ISO3 lookup)."""

    def test_lookup_country_by_iso3(self) -> None:
        result = lookup_country("UKR")
        assert result is not None
        assert result["name"] == "Ukraine"
        assert result["iso3"] == "UKR"
        assert result["iso2"] == "UA"

    def test_lookup_country_case_insensitive(self) -> None:
        result = lookup_country("ukr")
        assert result is not None
        assert result["iso3"] == "UKR"

    def test_lookup_country_unknown(self) -> None:
        result = lookup_country("ZZZ")
        assert result is None


class TestLookupGpe:
    """Tests for lookup_gpe (name-based lookup)."""

    def test_lookup_gpe_by_name(self) -> None:
        result = lookup_gpe("Ukraine")
        assert result is not None
        assert result["iso3"] == "UKR"

    def test_lookup_gpe_partial_name(self) -> None:
        result = lookup_gpe("United States")
        assert result is not None
        assert result["iso3"] == "USA"

    def test_lookup_gpe_unknown(self) -> None:
        result = lookup_gpe("Atlantis")
        assert result is None

    def test_lookup_gpe_common_countries(self) -> None:
        """Verify key geopolitical countries are all present."""
        expected = {
            "Russia": "RUS",
            "China": "CHN",
            "Iran": "IRN",
            "Israel": "ISR",
            "Syria": "SYR",
            "Turkey": "TUR",
        }
        for name, iso3 in expected.items():
            result = lookup_gpe(name)
            assert result is not None, f"{name} not found in geo data"
            assert result["iso3"] == iso3, (
                f"{name} returned {result['iso3']}, expected {iso3}"
            )


class TestGetRegion:
    """Tests for get_region (ISO3 to region)."""

    def test_get_region_from_iso3(self) -> None:
        assert get_region("UKR") == "Eastern Europe"
        assert get_region("USA") == "North America"
        assert get_region("IRN") == "Middle East"

    def test_get_region_unknown(self) -> None:
        assert get_region("ZZZ") is None
