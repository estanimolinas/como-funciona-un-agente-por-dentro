"""The search_code custom tool, exposed to the rag-search subagent as an in-process
MCP server per the Claude Agent SDK's custom-tool mechanism.

Note on the installed claude-agent-sdk API (0.2.95): `create_sdk_mcp_server` returns
an `McpSdkServerConfig` (fields: type, name, instance) whose `instance` is a
low-level `mcp.server.Server` object — it does NOT expose a `.tools` dict, so a
registered tool's handler cannot be reached from the returned server config. To keep
the tool callable directly testable, `_build_search_tool` constructs the
`SdkMcpTool` (which does have a `.handler` attribute) separately, and
`build_search_server` wraps it for `create_sdk_mcp_server`.

Also patches `mcp.server.Server` via `_mcp_compat.patch_mcp_server()` before calling
`create_sdk_mcp_server` - see that module's docstring for why: `create_sdk_mcp_server`
is written against the mainstream `mcp` SDK's low-level `Server` API, which this repo's
pinned `mcp==2.0.0` doesn't have.
"""
from __future__ import annotations

import asyncio
import sqlite3

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.orchestrator._mcp_compat import patch_mcp_server
from coderag_mcp.store.chunks import search_chunks
from coderag_mcp.store.db import run_db_sync


def _build_search_tool(conn: sqlite3.Connection, repo_id: int) -> SdkMcpTool:
    @tool(
        "search_code",
        "Semantic search over the indexed repo's code chunks. Returns the top "
        "matching functions/classes/methods with file path, line range, and source.",
        {"query": str, "top_k": int},
    )
    async def search_code(args: dict) -> dict:
        top_k = args.get("top_k", 5)
        query_embedding = (
            await asyncio.to_thread(embed_batch, [args["query"]], input_type="query")
        )[0]
        results = await run_db_sync(search_chunks, conn, repo_id, query_embedding, top_k)

        if not results:
            text = "No matches found."
        else:
            text = "\n\n".join(
                f"{r.file_path}:{r.start_line}-{r.end_line} "
                f"({r.symbol_type} {r.symbol_name})\n{r.signature}\n{r.source}"
                for r in results
            )
        return {"content": [{"type": "text", "text": text}]}

    return search_code


def build_search_server(conn: sqlite3.Connection, repo_id: int) -> McpSdkServerConfig:
    """Build the in-process SDK MCP server exposing `search_code`.

    Task 6 passes the result as `mcp_servers={"search": server}` to
    `ClaudeAgentOptions`, and references the tool by its SDK-qualified name
    `mcp__search__search_code`.
    """
    patch_mcp_server()
    return create_sdk_mcp_server(
        name="search", version="1.0.0", tools=[_build_search_tool(conn, repo_id)]
    )
