"""MCP server exposing CodeRAG-MCP's tools: ping (health check), index_repo,
search_code, ask_repo.

Note: the installed `mcp` SDK (2.0.0) no longer ships
`mcp.server.fastmcp.FastMCP` — that class was renamed/moved to
`mcp.server.mcpserver.MCPServer` in this major version. The public API
(``@mcp.tool()`` decorator, ``mcp.streamable_http_app()``) is otherwise
equivalent for our purposes.

Each tool gets its own shared, lazily-opened-once SQLite connection via this
MCPServer's own `lifespan=` parameter (confirmed against the installed SDK to
correctly fire through api/main.py's existing `async with
mcp_app.router.lifespan_context(mcp_app):` wrapping - no changes needed there).
This mirrors api/ask_route.py's app.state-based shared connection (see
coderag_mcp/api/deps.py) but is a *separate* connection object - the two transports
don't share one Python connection, they each avoid the same "reopen + reload
sqlite-vec per call" cost independently. Tools reach it via a `ctx: Context`
parameter and `ctx.request_context.lifespan_context.conn`.
"""
from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpserver import Context, MCPServer

from coderag_mcp.config import get_settings
from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.orchestrator.ask import ask as run_ask
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.store.chunks import search_chunks
from coderag_mcp.store.db import get_connection, init_schema, run_db_sync


@dataclass
class AppContext:
    conn: sqlite3.Connection


@asynccontextmanager
async def _lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    settings = get_settings()
    conn = get_connection(settings.sqlite_db_path)
    init_schema(conn)
    try:
        yield AppContext(conn=conn)
    finally:
        conn.close()


mcp = MCPServer("coderag-mcp", lifespan=_lifespan)


@mcp.tool()
def ping() -> str:
    """Trivial health-check tool: returns "pong"."""
    return "pong"


@mcp.tool()
async def index_repo(repo_url: str, ctx: Context) -> str:
    """Index a public GitHub/GitLab repo (clone, chunk, embed, store) if not already
    indexed. Returns its repo_id, reusable across search_code/ask_repo calls - though
    both of those also accept repo_url directly and index-on-first-use themselves."""
    conn = ctx.request_context.lifespan_context.conn
    repo_id = await run_db_sync(index_and_store_repo, conn, repo_url)
    return f"Indexed. repo_id={repo_id}"


@mcp.tool()
async def search_code(repo_url: str, query: str, ctx: Context, top_k: int = 5) -> str:
    """Semantic search over repo_url's indexed code chunks. Indexes repo_url first if
    this is the first call for it."""
    conn = ctx.request_context.lifespan_context.conn
    repo_id = await run_db_sync(index_and_store_repo, conn, repo_url)

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


@mcp.tool()
async def ask_repo(repo_url: str, question: str, ctx: Context) -> str:
    """Answer a question about repo_url using the single-agent orchestrator (semantic
    search + exact file reading). Indexes repo_url first if this is the first call for
    it."""
    conn = ctx.request_context.lifespan_context.conn
    repo_id = await run_db_sync(index_and_store_repo, conn, repo_url)
    return await run_ask(conn, repo_id, repo_url, question)
