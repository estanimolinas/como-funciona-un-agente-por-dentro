import asyncio

from unittest.mock import patch

from coderag_mcp.indexing.models import Chunk
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.orchestrator.tools import _build_search_tool, build_search_server
from coderag_mcp.store.db import get_connection, init_schema


def _chunk() -> Chunk:
    return Chunk(
        repo_url="https://github.com/a/b",
        file_path="mod.py",
        symbol_type="function",
        symbol_name="f",
        start_line=1,
        end_line=2,
        signature="def f():",
        source="def f():\n    pass",
    )


def _make_repo(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
    ):
        repo_id = index_and_store_repo(conn, "https://github.com/a/b")

    return conn, repo_id


def test_search_code_tool_returns_matching_chunk(tmp_path):
    conn, repo_id = _make_repo(tmp_path)

    # The installed claude-agent-sdk's create_sdk_mcp_server() returns an
    # McpSdkServerConfig whose `instance` is a low-level mcp.server.Server object
    # with no `.tools` dict exposed — so we reach the registered tool's callable
    # via the SdkMcpTool object itself (`_build_search_tool`), which is the same
    # object `build_search_server` wraps for `create_sdk_mcp_server`.
    search_tool = _build_search_tool(conn, repo_id)

    with patch(
        "coderag_mcp.orchestrator.search_service.embed_batch",
        return_value=[[1.0, 0.0, 0.0, 0.0]],
    ):
        result = asyncio.run(search_tool.handler({"query": "f", "top_k": 1}))

    assert "mod.py:1-2" in result["content"][0]["text"]


def test_search_code_tool_no_matches(tmp_path):
    conn, repo_id = _make_repo(tmp_path)
    search_tool = _build_search_tool(conn, repo_id)

    with patch(
        "coderag_mcp.orchestrator.search_service.embed_batch",
        return_value=[[0.0, 1.0, 0.0, 0.0]],
    ):
        result = asyncio.run(search_tool.handler({"query": "unrelated", "top_k": 0}))

    assert result["content"][0]["text"] == "No matches found."


def test_build_search_server_returns_sdk_config(tmp_path):
    conn, repo_id = _make_repo(tmp_path)
    server = build_search_server(conn, repo_id)

    # McpSdkServerConfig is a TypedDict, not an attrs/dataclass object.
    assert server["type"] == "sdk"
    assert server["name"] == "search"


def test_build_search_server_handlers_reachable_the_way_the_sdk_reaches_them(tmp_path):
    """Drives the compat `Server`'s `request_handlers` the same way
    `claude_agent_sdk._internal.query.Query._handle_sdk_mcp_request` does at
    runtime (tools/list then tools/call), instead of only checking that
    `build_search_server` returns a well-shaped config object. Proves the
    `mcp.server.Server` monkeypatch in `_mcp_compat.py` actually produces
    handlers usable end-to-end, not just importable.
    """
    from mcp import types

    conn, repo_id = _make_repo(tmp_path)
    server = build_search_server(conn, repo_id)
    instance = server["instance"]

    list_tools_handler = instance.request_handlers[types.ListToolsRequest]
    list_result = asyncio.run(list_tools_handler(None))
    tool_names = [t.name for t in list_result.root.tools]
    assert tool_names == ["search_code"]

    call_tool_handler = instance.request_handlers[types.CallToolRequest]
    with patch(
        "coderag_mcp.orchestrator.search_service.embed_batch",
        return_value=[[1.0, 0.0, 0.0, 0.0]],
    ):
        call_request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="search_code", arguments={"query": "f", "top_k": 1}
            ),
        )
        call_result = asyncio.run(call_tool_handler(call_request))

    assert "mod.py:1-2" in call_result.root.content[0].text
