"""Tests for CourtListener precedent lookup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from osint_core.services.courtlistener import CourtListenerClient, VerifiedCitation

SAMPLE_PRECEDENT_MAP = {
    "1A-free-speech": {
        "compelled_speech": [
            {"case": "West Virginia v. Barnette", "citation": "319 U.S. 624 (1943)"},
            {"case": "303 Creative LLC v. Elenis", "citation": "600 U.S. 570 (2023)"},
        ],
        "speech_codes": [
            {"case": "Tinker v. Des Moines", "citation": "393 U.S. 503 (1969)"},
        ],
    },
    "14A-due-process": {
        "campus_discipline": [
            {"case": "Goss v. Lopez", "citation": "419 U.S. 565 (1975)"},
        ],
    },
    "parental-rights": {
        "general": [
            {"case": "Troxel v. Granville", "citation": "530 U.S. 57 (2000)"},
        ],
    },
}


class TestMatchPrecedent:
    def test_matches_compelled_speech(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="1A-free-speech",
            constitutional_issue="Compelled speech — requires students to affirm beliefs",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert len(matches) >= 2
        assert matches[0]["case"] == "West Virginia v. Barnette"

    def test_matches_speech_codes(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="1A-free-speech",
            constitutional_issue="Speech code restricting campus expression",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert len(matches) >= 1
        assert any("Tinker" in m["case"] for m in matches)

    def test_falls_back_to_general(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="parental-rights",
            constitutional_issue="Parental notification bypass",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert len(matches) == 1
        assert "Troxel" in matches[0]["case"]

    def test_no_match_returns_empty(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="unknown-basis",
            constitutional_issue="Something",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert matches == []

    def test_caps_at_three(self) -> None:
        big_map = {
            "1A-free-speech": {
                "speech": [
                    {"case": f"Case {i}", "citation": f"Citation {i}"}
                    for i in range(10)
                ],
            },
        }
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="1A-free-speech",
            constitutional_issue="Speech restriction",
            precedent_map=big_map,
        )
        assert len(matches) == 3


class TestLookupPrecedent:
    @pytest.mark.asyncio
    async def test_verifies_matched_cases(self) -> None:
        client = CourtListenerClient()
        verified = VerifiedCitation(
            case_name="West Virginia v. Barnette",
            citation="319 U.S. 624 (1943)",
            courtlistener_url="https://www.courtlistener.com/opinion/123/",
            verified=True,
            holding_summary="Government cannot compel speech.",
        )
        with patch.object(
            client, "verify_citations", new_callable=AsyncMock, return_value=[verified]
        ):
            results = await client.lookup_precedent(
                constitutional_basis="1A-free-speech",
                constitutional_issue="Compelled speech requirement",
                precedent_map=SAMPLE_PRECEDENT_MAP,
            )
        assert len(results) >= 1
        assert results[0].verified is True
        assert "Barnette" in results[0].case_name

    @pytest.mark.asyncio
    async def test_returns_unverified_when_not_found(self) -> None:
        client = CourtListenerClient()
        with patch.object(client, "verify_citations", new_callable=AsyncMock, return_value=[]):
            results = await client.lookup_precedent(
                constitutional_basis="1A-free-speech",
                constitutional_issue="Compelled speech requirement",
                precedent_map=SAMPLE_PRECEDENT_MAP,
            )
        assert len(results) >= 1
        assert results[0].verified is False

    @pytest.mark.asyncio
    async def test_empty_when_no_matches(self) -> None:
        client = CourtListenerClient()
        results = await client.lookup_precedent(
            constitutional_basis="unknown",
            constitutional_issue="Nothing",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert results == []
