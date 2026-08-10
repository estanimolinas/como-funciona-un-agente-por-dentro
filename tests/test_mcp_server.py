"""End-to-end verification that the MCP server is reachable over Streamable HTTP.

This is the project's highest-risk integration point, so it is verified
against a real running server and a real MCP client — not mocked.
"""
from __future__ import annotations

import threading
import time

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from coderag_mcp.api.main import app, create_app

TEST_PORT = 8765


@pytest.fixture()
def live_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn server did not start in time"

    yield f"http://127.0.0.1:{TEST_PORT}/mcp"

    server.should_exit = True
    thread.join(timeout=5)


async def test_ping_tool_over_streamable_http(live_server):
    async with streamable_http_client(live_server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("ping", {})
            assert result.content[0].text == "pong"


def test_ping_tool_rejected_without_api_key(monkeypatch):
    from coderag_mcp.config import Settings

    monkeypatch.setattr(
        "coderag_mcp.api.auth.get_settings", lambda: Settings(coderag_api_key="secret123")
    )

    # Use a freshly-built app rather than the module-level `app` singleton:
    # the mcp SDK's StreamableHTTPSessionManager can only be `.run()` once per
    # instance, and `test_ping_tool_over_streamable_http` above already ran
    # the module-level app's session manager once via `live_server`.
    test_app = create_app()
    config = uvicorn.Config(test_app, host="127.0.0.1", port=TEST_PORT + 1, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn server did not start in time"

    try:
        import httpx

        response = httpx.post(
            f"http://127.0.0.1:{TEST_PORT + 1}/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 401
    finally:
        server.should_exit = True
        thread.join(timeout=5)
