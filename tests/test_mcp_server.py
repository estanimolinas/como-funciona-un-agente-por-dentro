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

from coderag_mcp.api.main import app

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
