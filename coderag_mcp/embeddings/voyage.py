"""Voyage AI embedding client for code chunks."""
from __future__ import annotations

import voyageai

from coderag_mcp.config import get_settings

MODEL = "voyage-code-3"


def embed_batch(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    """Embed texts with voyage-code-3.

    voyage-code-3 is an asymmetric model: pass input_type="document" when embedding
    the indexed corpus (the default, matching every existing indexing call site) and
    input_type="query" when embedding a search query - using the wrong side degrades
    retrieval quality without raising any error.
    """
    settings = get_settings()
    client = voyageai.Client(api_key=settings.voyage_api_key)
    result = client.embed(texts, model=MODEL, input_type=input_type)
    return result.embeddings
