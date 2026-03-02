"""Qdrant vectorization and semantic search service.

Uses sentence-transformers (all-MiniLM-L6-v2) to generate 384-dim embeddings
for OSINT events, and Qdrant for vector storage and similarity search.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from osint_core.config import settings

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Return the shared SentenceTransformer instance (lazy-loaded)."""
    global _model
    if _model is None:
        logger.info("Loading sentence-transformer model: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_text(text: str) -> list[float]:
    """Encode text into a fixed-length embedding vector.

    Args:
        text: Free-form text to embed.

    Returns:
        A list of floats with length ``EMBEDDING_DIM`` (384).
    """
    model = get_model()
    return model.encode(text).tolist()


def get_qdrant() -> QdrantClient:
    """Return a Qdrant client connected to the configured host."""
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def ensure_collection(client: QdrantClient) -> None:
    """Create the events collection if it does not already exist."""
    collections = [c.name for c in client.get_collections().collections]
    if settings.qdrant_collection not in collections:
        logger.info("Creating Qdrant collection: %s", settings.qdrant_collection)
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )


def upsert_event(event_id: str, text: str, payload: dict[str, Any]) -> None:
    """Embed text and upsert the event vector into Qdrant.

    Args:
        event_id: Unique event identifier (used as point ID via UUID5).
        text: Text to embed for this event.
        payload: Metadata dict stored alongside the vector.
    """
    vector = embed_text(text)
    client = get_qdrant()
    ensure_collection(client)

    # Derive a deterministic UUID from the event_id string
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, event_id))

    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={"event_id": event_id, **payload},
            )
        ],
    )
    logger.info("Upserted event %s into Qdrant (point %s)", event_id, point_id)


def search_similar(
    text: str,
    limit: int = 10,
    score_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Find events semantically similar to the given text.

    Args:
        text: Query text to embed and search against.
        limit: Maximum number of results to return.
        score_threshold: Minimum cosine similarity score.

    Returns:
        A list of dicts with keys ``id``, ``score``, and ``payload``.
    """
    vector = embed_text(text)
    client = get_qdrant()

    response = client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        limit=limit,
        score_threshold=score_threshold,
    )

    return [
        {
            "id": hit.id,
            "score": hit.score,
            "payload": hit.payload,
        }
        for hit in response.points
    ]
