"""POST /ask: index-on-first-use, then route the question through the orchestrator."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from coderag_mcp.api.auth import require_api_key
from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.schemas import AskRequest, AskResponse
from coderag_mcp.indexing.models import IndexingError
from coderag_mcp.orchestrator.ask import ask as run_ask
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo_async

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
async def ask_endpoint(
    request: AskRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> AskResponse:
    try:
        repo_id = await index_and_store_repo_async(conn, request.repo_url)
    except IndexingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - e.g. Voyage embedding failures
        logger.exception("indexing failed", extra={"repo_url": request.repo_url})
        raise HTTPException(
            status_code=502, detail="Could not index the repository."
        ) from exc

    try:
        answer = await run_ask(conn, repo_id, request.repo_url, request.question)
    except IndexingError as exc:
        # ask() re-clones the repo on every call (see orchestrator/ask.py); this
        # can fail with the same errors as the initial index even on a cache hit.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - any other orchestrator/subagent failure
        logger.exception("ask failed", extra={"repo_url": request.repo_url})
        raise HTTPException(
            status_code=502, detail="Could not answer the question."
        ) from exc

    return AskResponse(answer=answer)
