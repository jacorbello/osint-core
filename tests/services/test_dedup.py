"""Tests for near-duplicate detection via SimHash."""
import pytest
from osint_core.services.dedup import compute_simhash, simhash_distance, normalize_title


class TestNormalizeTitle:
    def test_lowercase_and_strip(self):
        assert normalize_title("  Hello WORLD  ") == "hello world"

    def test_strip_punctuation(self):
        result = normalize_title("Hello, World! — Test")
        assert "hello" in result
        assert "world" in result

    def test_empty(self):
        assert normalize_title("") == ""

    def test_none(self):
        assert normalize_title(None) == ""


class TestSimHash:
    def test_identical_titles_same_hash(self):
        h1 = compute_simhash("bombing in downtown austin texas")
        h2 = compute_simhash("bombing in downtown austin texas")
        assert h1 == h2

    def test_similar_titles_close_distance(self):
        h1 = compute_simhash("Snow and wind batter parts of US with threat of storms")
        h2 = compute_simhash("Snow and wind batter parts of US with threat of thunderstorms")
        assert simhash_distance(h1, h2) <= 12

    def test_different_titles_far_distance(self):
        h1 = compute_simhash("bombing in downtown austin texas")
        h2 = compute_simhash("new materials industry conference in jinan china")
        assert simhash_distance(h1, h2) > 12

    def test_empty_string(self):
        h = compute_simhash("")
        assert isinstance(h, int)
