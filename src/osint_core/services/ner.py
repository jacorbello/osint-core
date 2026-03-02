"""Named Entity Recognition (NER) service using spaCy.

Extracts PERSON, ORG, GPE, PRODUCT, and LOC entities from free-form OSINT
text. Uses the ``en_core_web_sm`` model by default.

The spaCy import is deferred to first use so that environments without spaCy
installed can still import the module (tests mock it).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MODEL_NAME = "en_core_web_sm"
ALLOWED_LABELS = frozenset({"PERSON", "ORG", "GPE", "PRODUCT", "LOC"})

_nlp: Any = None


def get_nlp() -> Any:
    """Return the shared spaCy NLP pipeline (lazy-loaded)."""
    global _nlp
    if _nlp is None:
        import spacy

        logger.info("Loading spaCy model: %s", MODEL_NAME)
        _nlp = spacy.load(MODEL_NAME)
    return _nlp


def extract_entities(text: str) -> list[dict[str, Any]]:
    """Extract named entities from text using spaCy NER.

    Args:
        text: Free-form text to analyze.

    Returns:
        A list of dicts with keys:
          - ``type``: Entity label (PERSON, ORG, GPE, PRODUCT, LOC).
          - ``name``: The entity text span.
          - ``start``: Start character offset in the input text.
          - ``end``: End character offset in the input text.
    """
    nlp = get_nlp()
    doc = nlp(text)
    return [
        {
            "type": ent.label_,
            "name": ent.text,
            "start": ent.start_char,
            "end": ent.end_char,
        }
        for ent in doc.ents
        if ent.label_ in ALLOWED_LABELS
    ]
