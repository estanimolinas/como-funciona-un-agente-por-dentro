"""Shared search_code logic, used by both real callers of it:
`orchestrator/tools.py`'s in-process SDK tool (exposed to the single-agent
orchestrator's `query()` run in `orchestrator/ask.py`) and `mcp_server/server.py`'s
real MCP `search_code` tool. Both used to implement this independently - embed the
query, search the repo's indexed chunks, format results - which let the same
db_lock-scope bug get fixed twice in this branch's history (commits 4f2889c and
c81859e). One implementation now, called from both places.
"""
from __future__ import annotations

import asyncio
import sqlite3

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.store.chunks import search_chunks
from coderag_mcp.store.db import run_db_sync

# Upper bound on top_k, regardless of what a caller (human, MCP client, or the
# orchestrator's own model) requests - keeps a single search from pulling the
# whole corpus into one response while holding db_lock.
MAX_TOP_K = 50


async def search_and_format(
    conn: sqlite3.Connection, repo_id: int, query: str, top_k: int = 5
) -> str:
    """Embed `query`, search `repo_id`'s indexed chunks, and return the results
    formatted as `file:line (type name)\\nsignature\\nsource` text blocks separated
    by blank lines, or "No matches found." if there are none.

    Two-step offload, in this order, to keep db_lock's held time as short as
    possible: embed the query via `asyncio.to_thread` (unlocked - this is a network
    call to Voyage, not a DB operation), then search via `run_db_sync` (locked -
    this is the only part that touches the shared sqlite connection).
    """
    top_k = min(top_k, MAX_TOP_K)
    query_embedding = (
        await asyncio.to_thread(embed_batch, [query], input_type="query")
    )[0]
    results = await run_db_sync(search_chunks, conn, repo_id, query_embedding, top_k)

    if not results:
        return "No matches found."
    return "\n\n".join(
        f"{r.file_path}:{r.start_line}-{r.end_line} ({r.symbol_type} {r.symbol_name})\n"
        f"{r.signature}\n{r.source}"
        for r in results
    )
