"""Voyage AI embedding client for code chunks."""
from __future__ import annotations

import voyageai

from coderag_mcp.config import get_settings

MODEL = "voyage-code-3"


def embed_batch(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    client = voyageai.Client(api_key=settings.voyage_api_key)
    result = client.embed(texts, model=MODEL, input_type="document")
    return result.embeddings
