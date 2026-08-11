"""End-to-end tests for POST /ask/stream against a real running app - proves the
SSE wire format and endpoint wiring work, mocking the expensive domain calls the
same way this project's other transport tests do."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from unittest.mock import patch

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.main import app, create_app
from coderag_mcp.config import Settings
from coderag_mcp.indexing.models import InvalidRepoURLError
from coderag_mcp.store.db import get_connection, init_schema
from coderag_mcp.store.repos import create_repo

LIVE_STREAM_TEST_PORT = 8770


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
    duration = events[1]["duration_s"]
    assert isinstance(duration, float)
    assert round(duration, 2) == duration


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


async def _fake_ask_stream_with_delay(conn, repo_id, repo_url, question):
    """Yields 3 answer_token events with a real await between each, so a test can
    prove the HTTP response is actually flushed incrementally (not buffered until
    the whole generator finishes) - fastapi.testclient.TestClient's fully-buffered
    response.text read can't distinguish those two cases, hence the real live
    server + real httpx streaming client below."""
    for i in range(3):
        await asyncio.sleep(0.1)
        yield {"type": "answer_token", "text": f"chunk {i}"}
    yield {"type": "done"}


@pytest.fixture()
def live_stream_server(tmp_path, monkeypatch):
    # Patch before starting the server thread: `patch(...)` just reassigns module
    # attributes, which is visible across threads in the same process (the live
    # server runs on a background thread of this same process, not a subprocess),
    # so keeping the patches active for the fixture's lifetime works correctly -
    # same reasoning tests/test_mcp_server.py's live_server fixture relies on for
    # its own monkeypatch-before-start-server pattern.
    monkeypatch.setattr(
        "coderag_mcp.api.main.get_settings",
        lambda: Settings(sqlite_db_path=str(tmp_path / "live_stream_test.db")),
    )

    with (
        patch("coderag_mcp.api.ask_stream_route.index_and_store_repo_async", return_value=1),
        patch(
            "coderag_mcp.api.ask_stream_route.ask_stream",
            side_effect=_fake_ask_stream_with_delay,
        ),
    ):
        test_app = create_app()
        config = uvicorn.Config(
            test_app, host="127.0.0.1", port=LIVE_STREAM_TEST_PORT, log_level="warning"
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.time() + 5
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn server did not start in time"

        yield f"http://127.0.0.1:{LIVE_STREAM_TEST_PORT}/ask/stream"

        server.should_exit = True
        thread.join(timeout=5)


def test_ask_stream_delivers_events_incrementally_over_a_real_socket(live_stream_server):
    """Proves the SSE response is genuinely streamed - each answer_token event
    arrives as it's produced (with the mocked ask_stream()'s real 0.1s sleeps
    between them), not all at once after FastAPI/Starlette finish buffering the
    whole generator. A TestClient-based test could pass identically either way,
    since TestClient's response.text reads the fully-collected body - this test
    uses a real running uvicorn server and a real httpx streaming client instead,
    recording wall-clock arrival times for each event."""
    arrival_times: list[float] = []
    event_types: list[str] = []

    with httpx.Client(timeout=10.0) as client:
        with client.stream(
            "POST",
            live_stream_server,
            json={"repo_url": "https://github.com/a/b", "question": "how does X work?"},
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("data: "):
                    arrival_times.append(time.monotonic())
                    event_types.append(json.loads(line[len("data: "):])["type"])

    # indexing_start, indexing_done, 3x answer_token, done
    assert event_types == [
        "indexing_start",
        "indexing_done",
        "answer_token",
        "answer_token",
        "answer_token",
        "done",
    ]

    # The 3 answer_token events are separated by real 0.1s sleeps server-side.
    # Assert a real gap exists between the first and last answer_token arrival -
    # comfortably below the 0.2s (2 * 0.1s) total delay between them, but well
    # above zero, so this can't pass if the whole body were buffered and sent as
    # one chunk (which would put all arrival times within microseconds of each
    # other regardless of the mocked generator's sleeps).
    first_answer_token_time = arrival_times[event_types.index("answer_token")]
    last_answer_token_time = arrival_times[len(event_types) - 1 - event_types[::-1].index("answer_token")]
    assert last_answer_token_time - first_answer_token_time > 0.05
