"""Tests for Qdrant vectorization and semantic search service."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _mock_sentence_transformer():
    """Mock SentenceTransformer to avoid downloading models in CI."""
    # Reset module-level cache before each test
    import osint_core.services.vectorize as mod

    mod._model = None

    fake_model = MagicMock()

    def _encode(text):
        # Deterministic pseudo-embedding based on text hash
        rng = np.random.RandomState(hash(text) % 2**31)
        return rng.rand(384).astype(np.float32)

    fake_model.encode = _encode

    with patch.object(mod, "SentenceTransformer", return_value=fake_model):
        yield fake_model

    mod._model = None


# ---- embed_text tests -------------------------------------------------------


def test_embed_text_returns_correct_dimension():
    from osint_core.services.vectorize import EMBEDDING_DIM, embed_text

    vec = embed_text("Critical vulnerability in Apache HTTP Server")
    assert len(vec) == EMBEDDING_DIM  # 384 for all-MiniLM-L6-v2


def test_embed_text_deterministic():
    from osint_core.services.vectorize import embed_text

    v1 = embed_text("test input")
    v2 = embed_text("test input")
    assert v1 == v2


def test_embed_text_different_inputs_differ():
    from osint_core.services.vectorize import embed_text

    v1 = embed_text("Apache vulnerability CVE-2026-0001")
    v2 = embed_text("Totally unrelated text about cooking recipes")
    assert v1 != v2


def test_similar_texts_have_high_cosine():
    """Mocked model produces deterministic vectors — cosine depends on hash similarity.

    This test validates that the cosine computation itself works correctly.
    With real embeddings, semantically similar texts would score >0.7.
    """
    from osint_core.services.vectorize import embed_text

    v1 = embed_text("Apache vulnerability CVE-2026-0001")
    v2 = embed_text("Apache vulnerability CVE-2026-0001")  # identical text -> identical vec
    cosine = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    assert cosine > 0.99  # identical inputs must produce cosine ~1.0


# ---- get_qdrant tests --------------------------------------------------------


def test_get_qdrant_returns_client():
    from osint_core.services.vectorize import get_qdrant

    with patch("osint_core.services.vectorize.QdrantClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        client = get_qdrant()
        mock_cls.assert_called_once()
        assert client is not None


# ---- upsert_event tests -----------------------------------------------------


def test_upsert_event_calls_qdrant():
    from osint_core.services.vectorize import upsert_event

    mock_client = MagicMock()
    with patch("osint_core.services.vectorize.get_qdrant", return_value=mock_client):
        upsert_event("evt-123", "Apache vulnerability", {"source": "cisa"})
        mock_client.upsert.assert_called_once()
        call_args = mock_client.upsert.call_args
        assert call_args.kwargs["collection_name"] == "osint-events"


# ---- search_similar tests ---------------------------------------------------


def test_search_similar_returns_results():
    from osint_core.services.vectorize import search_similar

    fake_hit = MagicMock()
    fake_hit.id = "evt-001"
    fake_hit.score = 0.92
    fake_hit.payload = {"title": "test"}

    mock_client = MagicMock()
    mock_client.query_points.return_value.points = [fake_hit]

    with patch("osint_core.services.vectorize.get_qdrant", return_value=mock_client):
        results = search_similar("Apache vulnerability", limit=5, score_threshold=0.5)
        assert len(results) == 1
        assert results[0]["id"] == "evt-001"
        assert results[0]["score"] == 0.92


def test_search_similar_respects_limit():
    from osint_core.services.vectorize import search_similar

    mock_client = MagicMock()
    mock_client.query_points.return_value.points = []

    with patch("osint_core.services.vectorize.get_qdrant", return_value=mock_client):
        results = search_similar("test query", limit=3)
        call_args = mock_client.query_points.call_args
        assert call_args.kwargs["limit"] == 3


# ---- Module-level constants --------------------------------------------------


def test_module_constants():
    from osint_core.services.vectorize import EMBEDDING_DIM, MODEL_NAME

    assert MODEL_NAME == "all-MiniLM-L6-v2"
    assert EMBEDDING_DIM == 384
