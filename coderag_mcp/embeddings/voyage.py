"""Voyage AI embedding client for code chunks."""
from __future__ import annotations

import logging
import time

import voyageai
import voyageai.error

from coderag_mcp.config import get_settings

MODEL = "voyage-code-3"
MAX_ATTEMPTS = 3

_RETRYABLE_ERRORS = (
    voyageai.error.APIConnectionError,
    voyageai.error.RateLimitError,
    voyageai.error.ServerError,
    voyageai.error.ServiceUnavailableError,
    voyageai.error.Timeout,
    voyageai.error.TryAgain,
)

logger = logging.getLogger(__name__)

_client: voyageai.Client | None = None


def _get_client() -> voyageai.Client:
    """Lazily initialize and return the shared Voyage client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


def embed_batch(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    """Embed texts with voyage-code-3.

    voyage-code-3 is an asymmetric model: pass input_type="document" when embedding
    the indexed corpus (the default, matching every existing indexing call site) and
    input_type="query" when embedding a search query - using the wrong side degrades
    retrieval quality without raising any error.

    Retries up to MAX_ATTEMPTS times, with exponential backoff, on transient
    voyageai.error types only (connection/timeout/rate-limit/server errors) -
    anything else (auth failures, malformed requests) fails immediately, since
    retrying those wastes time and can't succeed.

    Caveat: this backoff is tuned for transient connection/server errors, not
    for sustained per-minute rate limits (Voyage's actual limits are
    per-minute, e.g. 3 RPM/10K TPM on accounts without a payment method). A
    single large embed_batch call that exceeds a token-per-minute cap will
    exhaust all retries in a few seconds rather than actually recovering,
    since the backoff delays here can't outlast a per-minute window. The real
    fix for that - batching large chunk sets into multiple smaller requests -
    is a known deferred item, not implemented here.
    """
    client = _get_client()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = client.embed(texts, model=MODEL, input_type=input_type)
            return result.embeddings
        except _RETRYABLE_ERRORS as exc:
            if attempt == MAX_ATTEMPTS:
                logger.error(
                    "embed_batch failed after %d attempts: %s",
                    MAX_ATTEMPTS,
                    exc,
                    extra={"attempt": attempt, "error_type": type(exc).__name__},
                    exc_info=True,
                )
                raise
            delay = 2 ** (attempt - 1)  # 1s, 2s, 4s, ... scales with MAX_ATTEMPTS
            logger.warning(
                "embed_batch attempt %d/%d failed, retrying in %.0fs: %s",
                attempt,
                MAX_ATTEMPTS,
                delay,
                exc,
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            time.sleep(delay)

    # Unreachable: the loop always returns or raises above.
    raise AssertionError("unreachable")
