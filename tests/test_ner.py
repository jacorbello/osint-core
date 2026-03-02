"""Tests for spaCy NER entity extraction service.

The spaCy model (en_core_web_sm) may not be installed in CI, so all tests
mock the spaCy pipeline. The implementation uses a lazy import so that the
module can be loaded without spaCy present.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_mock_entity(text: str, label: str, start_char: int, end_char: int):
    """Create a mock spaCy entity span."""
    ent = MagicMock()
    ent.text = text
    ent.label_ = label
    ent.start_char = start_char
    ent.end_char = end_char
    return ent


def _build_mock_nlp():
    """Build a mock NLP pipeline that simulates spaCy NER."""
    known_entities: dict[str, str] = {
        "John Smith": "PERSON",
        "Microsoft": "ORG",
        "Acme Corp": "ORG",
        "Google": "ORG",
        "CISA": "ORG",
        "United States": "GPE",
        "Russia": "GPE",
        "China": "GPE",
        "Windows Server": "PRODUCT",
        "Apache HTTP Server": "PRODUCT",
    }

    def mock_nlp(text: str):
        entities = []
        for name, label in known_entities.items():
            idx = text.find(name)
            if idx >= 0:
                entities.append(_make_mock_entity(name, label, idx, idx + len(name)))
        doc = MagicMock()
        doc.ents = entities
        return doc

    return mock_nlp


@pytest.fixture(autouse=True)
def _mock_spacy_pipeline():
    """Patch get_nlp to return a mock NLP pipeline."""
    import osint_core.services.ner as mod

    mod._nlp = None

    mock_nlp = _build_mock_nlp()

    with patch.object(mod, "get_nlp", return_value=mock_nlp):
        yield

    mod._nlp = None


# ---- extract_entities tests --------------------------------------------------


def test_extract_person():
    from osint_core.services.ner import extract_entities

    text = "John Smith, CEO of Acme Corp, announced the vulnerability disclosure."
    entities = extract_entities(text)
    assert any(e["type"] == "PERSON" and "John Smith" in e["name"] for e in entities)


def test_extract_org():
    from osint_core.services.ner import extract_entities

    text = "Microsoft released a security patch for Windows Server."
    entities = extract_entities(text)
    assert any(e["type"] == "ORG" and "Microsoft" in e["name"] for e in entities)


def test_extract_product():
    from osint_core.services.ner import extract_entities

    text = "Critical vulnerability in Apache HTTP Server allows remote code execution."
    entities = extract_entities(text)
    assert any(
        e["type"] == "PRODUCT" and "Apache HTTP Server" in e["name"] for e in entities
    )


def test_extract_gpe():
    from osint_core.services.ner import extract_entities

    text = "CISA warned that threat actors from Russia are targeting US infrastructure."
    entities = extract_entities(text)
    assert any(e["type"] == "GPE" and "Russia" in e["name"] for e in entities)


def test_extract_multiple_entities():
    from osint_core.services.ner import extract_entities

    text = "John Smith at Microsoft reported a vulnerability in Windows Server."
    entities = extract_entities(text)
    types = {e["type"] for e in entities}
    assert "PERSON" in types
    assert "ORG" in types


def test_extract_entities_returns_dict_format():
    from osint_core.services.ner import extract_entities

    text = "Microsoft released a patch."
    entities = extract_entities(text)
    assert len(entities) > 0
    ent = entities[0]
    assert "type" in ent
    assert "name" in ent
    assert "start" in ent
    assert "end" in ent


def test_extract_no_entities():
    from osint_core.services.ner import extract_entities

    text = "some random text with no recognizable entities"
    entities = extract_entities(text)
    assert entities == []


def test_extract_filters_unwanted_labels():
    """Only PERSON, ORG, GPE, PRODUCT, LOC should be returned."""
    from osint_core.services.ner import ALLOWED_LABELS

    assert "PERSON" in ALLOWED_LABELS
    assert "ORG" in ALLOWED_LABELS
    assert "GPE" in ALLOWED_LABELS
    assert "PRODUCT" in ALLOWED_LABELS
    assert "LOC" in ALLOWED_LABELS
    # Common spaCy labels that should NOT appear
    assert "DATE" not in ALLOWED_LABELS
    assert "CARDINAL" not in ALLOWED_LABELS
    assert "MONEY" not in ALLOWED_LABELS
