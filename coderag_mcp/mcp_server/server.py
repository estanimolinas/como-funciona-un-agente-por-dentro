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

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpserver import Context, MCPServer

from coderag_mcp.config import get_settings
from coderag_mcp.indexing.models import IndexingError
from coderag_mcp.logging_config import configure_logging
from coderag_mcp.orchestrator.ask import ask as run_ask
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo_async
from coderag_mcp.orchestrator.search_service import search_and_format
from coderag_mcp.store.db import get_connection, init_schema


@dataclass
class AppContext:
    conn: sqlite3.Connection


@asynccontextmanager
async def _lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    configure_logging()
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
    indexed. Returns a confirmation with the internal repo_id (informational only -
    search_code and ask_repo take repo_url directly and index on first use, no
    repo_id needed)."""
    conn = ctx.request_context.lifespan_context.conn
    try:
        repo_id = await index_and_store_repo_async(conn, repo_url)
    except IndexingError as exc:
        # IndexingError messages are client-safe by design (see
        # coderag_mcp/indexing/models.py) - matches api/ask_route.py's precedent.
        return str(exc)
    except Exception:  # noqa: BLE001 - e.g. Voyage embedding failures
        return "Could not index the repository."
    return f"Indexed. repo_id={repo_id}"


@mcp.tool()
async def search_code(repo_url: str, query: str, ctx: Context, top_k: int = 5) -> str:
    """Semantic search over repo_url's indexed code chunks. Indexes repo_url first if
    this is the first call for it."""
    conn = ctx.request_context.lifespan_context.conn
    try:
        repo_id = await index_and_store_repo_async(conn, repo_url)
    except IndexingError as exc:
        return str(exc)
    except Exception:  # noqa: BLE001
        return "Could not index the repository."

    try:
        return await search_and_format(conn, repo_id, query, top_k)
    except Exception:  # noqa: BLE001 - e.g. Voyage embedding failures
        return "Could not search the repository."


@mcp.tool()
async def ask_repo(repo_url: str, question: str, ctx: Context) -> str:
    """Answer a question about repo_url using the single-agent orchestrator (semantic
    search + exact file reading). Indexes repo_url first if this is the first call for
    it."""
    conn = ctx.request_context.lifespan_context.conn
    try:
        repo_id = await index_and_store_repo_async(conn, repo_url)
    except IndexingError as exc:
        return str(exc)
    except Exception:  # noqa: BLE001
        return "Could not index the repository."

    try:
        return await run_ask(conn, repo_id, repo_url, question)
    except IndexingError as exc:
        # ask() re-clones the repo on every call (see orchestrator/ask.py); this
        # can fail with the same errors as the initial index even on a cache hit.
        return str(exc)
    except Exception:  # noqa: BLE001 - any other orchestrator/subagent failure
        return "Could not answer the question."
