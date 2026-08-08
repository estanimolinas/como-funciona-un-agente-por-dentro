"""MCP server exposing CodeRAG-MCP's tools.

This starts with one dummy tool to validate the Streamable HTTP protocol
integration end-to-end before the real indexing/search/ask tools are built
on top of it in a later plan.

Note: the installed `mcp` SDK (2.0.0) no longer ships
`mcp.server.fastmcp.FastMCP` — that class was renamed/moved to
`mcp.server.mcpserver.MCPServer` in this major version. The public API
(``@mcp.tool()`` decorator, ``mcp.streamable_http_app()``) is otherwise
equivalent for our purposes.
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("coderag-mcp")


@mcp.tool()
def ping() -> str:
    """Trivial health-check tool: returns "pong"."""
    return "pong"
