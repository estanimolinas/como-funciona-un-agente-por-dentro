"""End-to-end tests for POST /ask/stream against a real running app - proves the
SSE wire format and endpoint wiring work, mocking the expensive domain calls the
same way this project's other transport tests do."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.main import app
from coderag_mcp.indexing.models import InvalidRepoURLError
from coderag_mcp.store.db import get_connection, init_schema
from coderag_mcp.store.repos import create_repo


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@pytest.fixture()
def client(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)
    app.dependency_overrides[get_db_conn] = lambda: conn
    try:
        yield TestClient(app), conn
    finally:
        del app.dependency_overrides[get_db_conn]
        conn.close()


async def _fake_ask_stream(conn, repo_id, repo_url, question):
    yield {"type": "tool_call", "tool": "search_code", "input": {"query": question}}
    yield {"type": "tool_result", "tool_use_id": "t1", "output_preview": "found it"}
    yield {"type": "answer_token", "text": "The answer "}
    yield {"type": "answer_token", "text": "is here."}
    yield {"type": "done"}


def test_ask_stream_indexes_then_streams_orchestrator_events(client):
    test_client, conn = client
    with (
        patch("coderag_mcp.api.ask_stream_route.index_and_store_repo_async", return_value=1),
        patch("coderag_mcp.api.ask_stream_route.ask_stream", side_effect=_fake_ask_stream),
    ):
        response = test_client.post(
            "/ask/stream",
            json={"repo_url": "https://github.com/a/b", "question": "how does X work?"},
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    types = [e["type"] for e in events]
    assert types == [
        "indexing_start",
        "indexing_done",
        "tool_call",
        "tool_result",
        "answer_token",
        "answer_token",
        "done",
    ]
    assert events[0]["repo_url"] == "https://github.com/a/b"
    assert events[2]["tool"] == "search_code"


def test_ask_stream_skips_indexing_events_on_cache_hit(client):
    test_client, conn = client
    create_repo(conn, "https://github.com/a/b")

    with patch("coderag_mcp.api.ask_stream_route.ask_stream", side_effect=_fake_ask_stream):
        response = test_client.post(
            "/ask/stream",
            json={"repo_url": "https://github.com/a/b", "question": "?"},
        )

    types = [e["type"] for e in _parse_sse(response.text)]
    assert "indexing_start" not in types
    assert "indexing_done" not in types
    assert types[0] == "tool_call"


def test_ask_stream_emits_error_event_on_indexing_failure(client):
    test_client, _conn = client
    with patch(
        "coderag_mcp.api.ask_stream_route.index_and_store_repo_async",
        side_effect=InvalidRepoURLError("bad host"),
    ):
        response = test_client.post(
            "/ask/stream",
            json={"repo_url": "https://evil.example/a/b", "question": "?"},
        )

    events = _parse_sse(response.text)
    assert events[-1] == {"type": "error", "message": "bad host"}


def test_ask_stream_emits_error_event_on_mid_stream_failure(client):
    test_client, conn = client
    # Pre-cache the repo so indexing is skipped - this test isolates a mid-stream
    # ask_stream() failure, not indexing behavior (covered separately above).
    create_repo(conn, "https://github.com/a/b")

    async def _failing_ask_stream(conn, repo_id, repo_url, question):
        yield {"type": "tool_call", "tool": "search_code", "input": {}}
        raise RuntimeError("sdk exploded")

    with (
        patch("coderag_mcp.api.ask_stream_route.index_and_store_repo_async", return_value=1),
        patch("coderag_mcp.api.ask_stream_route.ask_stream", side_effect=_failing_ask_stream),
    ):
        response = test_client.post(
            "/ask/stream",
            json={"repo_url": "https://github.com/a/b", "question": "?"},
        )

    events = _parse_sse(response.text)
    assert events[0]["type"] == "tool_call"
    assert events[-1] == {"type": "error", "message": "Could not answer the question."}
