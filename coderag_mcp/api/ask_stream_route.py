"""POST /ask/stream: the same job as POST /ask, but streams the orchestrator's
live progress (indexing, tool calls, tool results, reasoning, and the answer
token-by-token) as Server-Sent Events instead of waiting for a final answer."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from coderag_mcp.api.auth import require_api_key
from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.schemas import AskRequest
from coderag_mcp.indexing.models import IndexingError
from coderag_mcp.orchestrator.ask import ask_stream
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo_async
from coderag_mcp.store import repos as repo_store
from coderag_mcp.store.chunks import count_chunks
from coderag_mcp.store.db import run_db_sync

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream_events(conn: sqlite3.Connection, request: AskRequest) -> AsyncIterator[str]:
    try:
        existing_id = await run_db_sync(repo_store.get_repo_id_by_url, conn, request.repo_url)

        if existing_id is None:
            yield _sse({"type": "indexing_start", "repo_url": request.repo_url})
            start = time.monotonic()
            try:
                repo_id = await index_and_store_repo_async(conn, request.repo_url)
            except IndexingError as exc:
                yield _sse({"type": "error", "message": str(exc)})
                return
            except Exception:  # noqa: BLE001 - e.g. Voyage embedding failures
                logger.exception("indexing failed", extra={"repo_url": request.repo_url})
                yield _sse({"type": "error", "message": "Could not index the repository."})
                return
            chunk_count = await run_db_sync(count_chunks, conn, repo_id)
            yield _sse({
                "type": "indexing_done",
                "chunk_count": chunk_count,
                "duration_s": round(time.monotonic() - start, 2),
            })
        else:
            repo_id = existing_id

        try:
            async for event in ask_stream(conn, repo_id, request.repo_url, request.question):
                yield _sse(event)
        except IndexingError as exc:
            # ask_stream() re-clones the repo on every call; this can fail with the
            # same errors as the initial index even on a cache hit.
            yield _sse({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001 - any other orchestrator/subagent failure
            logger.exception("ask_stream failed", extra={"repo_url": request.repo_url})
            yield _sse({"type": "error", "message": "Could not answer the question."})
    except Exception:  # noqa: BLE001 - defensive: never leave the SSE connection hanging
        logger.exception("unexpected failure in /ask/stream", extra={"repo_url": request.repo_url})
        yield _sse({"type": "error", "message": "Something went wrong."})


@router.post("/ask/stream", dependencies=[Depends(require_api_key)])
async def ask_stream_endpoint(
    request: AskRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> StreamingResponse:
    return StreamingResponse(
        _stream_events(conn, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
