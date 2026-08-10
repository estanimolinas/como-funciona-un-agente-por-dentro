"""Compatibility shim for `claude_agent_sdk.create_sdk_mcp_server()` against the
`mcp==2.0.0` package pinned in this repo's `pyproject.toml`.

That `mcp` version's `mcp.server.Server` (aka `mcp.server.lowlevel.server.Server`) has
a different internal API from the mainstream `mcp` SDK (see CLAUDE.md's documented
`MCPServer`/`FastMCP` gotcha for the same class of issue) - it registers handlers via
`add_request_handler(method: str, params_type, handler)` instead of exposing
`.list_tools()`/`.call_tool()` decorators backed by a public `.request_handlers: dict[type,
Callable]`. `claude_agent_sdk.create_sdk_mcp_server()` (installed version 0.2.95) is
written against the mainstream shape and does `from mcp.server import Server` internally,
so it breaks against this repo's pinned `mcp` version.

A second, separate divergence in the same fork: mainstream `mcp.types.ServerResult` is a
pydantic `RootModel[Union[...]]` wrapper (constructible, with a `.root` attribute holding
the actual result). In this fork, `mcp.types.ServerResult` is a plain `typing` union alias
(a `types.UnionType`, not callable). `claude_agent_sdk._internal.query.Query.
_handle_sdk_mcp_request` (the code that actually drives these handlers at runtime) expects
the mainstream shape - it calls the handler and then reads `result.root.tools` /
`result.root.content`. `_ServerResult` below is a minimal stand-in that provides that
`.root` attribute without depending on `mcp.types.ServerResult` being callable.

`Server` here reimplements just the slice of the mainstream API that
`create_sdk_mcp_server()` and `_handle_sdk_mcp_request` actually touch: construction,
`.name`/`.version`, `.request_handlers`, and the `list_tools`/`call_tool` decorators.
`mcp.types`'s individual result/request models (`Tool`, `ListToolsResult`,
`CallToolResult`, etc.) are unaffected by the fork and are reused as-is - only the
`ServerResult` wrapper needed a substitute.

Nothing else in this project imports `mcp.server.Server` - `coderag_mcp/mcp_server/server.py`
uses the unrelated `mcp.server.mcpserver.MCPServer` - so patching this symbol is scoped to
the orchestrator's in-process tool server and does not affect the existing `/mcp` endpoint.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp import types


@dataclass
class _ServerResult:
    root: Any


class Server:
    def __init__(self, name: str, version: str | None = None):
        self.name = name
        self.version = version
        self.request_handlers: dict[type, Callable[..., Awaitable[_ServerResult]]] = {}

    def list_tools(self):
        def decorator(func: Callable[[], Awaitable[list[types.Tool]]]):
            async def handler(_req: types.ListToolsRequest | None) -> _ServerResult:
                tools = await func()
                return _ServerResult(root=types.ListToolsResult(tools=tools))

            self.request_handlers[types.ListToolsRequest] = handler
            return func

        return decorator

    def call_tool(self):
        def decorator(
            func: Callable[[str, dict[str, Any]], Awaitable[types.CallToolResult]],
        ):
            async def handler(req: types.CallToolRequest) -> _ServerResult:
                result = await func(req.params.name, req.params.arguments or {})
                return _ServerResult(root=result)

            self.request_handlers[types.CallToolRequest] = handler
            return func

        return decorator


def patch_mcp_server() -> None:
    """Point `mcp.server.Server` at the compat shim above.

    Call this before `claude_agent_sdk.create_sdk_mcp_server()`, whose internal
    `from mcp.server import Server` re-resolves the module attribute on every call.
    """
    import mcp.server

    mcp.server.Server = Server
