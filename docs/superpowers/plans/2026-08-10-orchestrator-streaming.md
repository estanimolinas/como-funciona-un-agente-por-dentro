# Orchestrator Live Streaming (SSE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ask_stream()` (the single source of truth for the Claude Agent SDK
interaction, yielding structured events live) and a new `POST /ask/stream` SSE
endpoint, per `docs/superpowers/specs/2026-08-10-orchestrator-streaming-design.md`.

**Architecture:** `orchestrator/ask.py`'s `ask()` becomes a thin wrapper over a new
`ask_stream()` async generator, which does the real SDK interaction and yields one
event per tool call, tool result, reasoning block, and answer token (real token-level
streaming, confirmed available via `ClaudeAgentOptions(include_partial_messages=True)`
+ `StreamEvent`). A new endpoint drives indexing (with its own start/done events) then
streams `ask_stream()`'s events as Server-Sent Events.

**Tech Stack:** `claude-agent-sdk` (already installed), FastAPI's `StreamingResponse`,
stdlib `json`.

## Global Constraints

- `ask()`'s existing signature and external behavior are unchanged — `/ask` and the
  MCP `ask_repo` tool must keep working exactly as today, and their existing tests
  must pass unchanged, not just "still pass with modifications."
- `ask_stream()` does not itself catch and convert exceptions into `error` events —
  it logs and re-raises exactly like `ask()` does today (e.g. on timeout). Converting
  an exception into a safe `error` event is the SSE endpoint's job, not
  `ask_stream()`'s — this mirrors `api/ask_route.py`'s existing pattern (the
  `IndexingError` → safe-message / generic-`Exception` → safe-message split already
  used there) and keeps `ask_stream()` a plain, honestly-typed async generator that
  either yields events or raises.
- Every SSE message is `data: <json>\n\n` with a `type` discriminant field, per the
  spec's exact event schema. `output_preview` (on `tool_result` events) is truncated
  to 400 characters with a truncation marker if longer.
- The following `claude_agent_sdk` shapes were confirmed against the installed SDK by
  running a real, live orchestrator query while writing this plan (not assumed) —
  trust these, but re-verify if your installed SDK version differs:
  - `AssistantMessage.content` is a list that can contain `TextBlock`, `ThinkingBlock`,
    and `ToolUseBlock` (among other block types this project doesn't use).
    `ToolUseBlock` requests (`id`, `name`, `input`) appear here.
  - `ToolResultBlock` (`tool_use_id`, `content: str | list[dict] | None`, `is_error`)
    appears inside **`UserMessage.content`**, not `AssistantMessage.content` — the
    SDK feeds tool results back as a user-role turn, matching the underlying Anthropic
    API's convention.
  - With `ClaudeAgentOptions(include_partial_messages=True)`, `query()` also yields
    `StreamEvent(uuid, session_id, event: dict, parent_tool_use_id)` messages
    carrying the raw Anthropic API streaming protocol: `event["type"]` is one of
    `"content_block_start"` (has `event["index"]` and
    `event["content_block"]["type"]` — `"text"`, `"thinking"`, or `"tool_use"`),
    `"content_block_delta"` (has `event["index"]` and `event["delta"]`, where
    `event["delta"]["type"]` is `"text_delta"` with `event["delta"]["text"]` for
    real token-by-token answer text, or `"thinking_delta"`/`"input_json_delta"` for
    the other block types — this plan only uses the `text_delta` case),
    `"content_block_stop"`, `"message_start"`, `"message_delta"`, `"message_stop"`.
  - Also present in a real stream but irrelevant to this feature and never mapped to
    any event: `HookEventMessage`, `SystemMessage` (various subtypes),
    `RateLimitEvent`, `ResultMessage`. `ask_stream()` silently ignores all of these.
- Full test suite (currently 88/88) must stay green after every task.

---

### Task 1: `ask_stream()` — the streaming orchestrator core, `ask()` as a thin wrapper

**Files:**
- Modify: `coderag_mcp/orchestrator/ask.py`
- Test: `tests/orchestrator/test_ask.py`

**Interfaces:**
- Produces: `ask_stream(conn: sqlite3.Connection, repo_id: int, repo_url: str,
  question: str, *, timeout_s: float = 180.0) -> AsyncIterator[dict[str, Any]]` and
  `ask(conn, repo_id, repo_url, question, *, timeout_s: float = 180.0) -> str`
  (signature unchanged from today) in `coderag_mcp/orchestrator/ask.py`. Task 2
  imports and consumes `ask_stream`.

- [x] **Step 1: Write the failing tests for `ask_stream()`'s event mapping**

Add to `tests/orchestrator/test_ask.py` (keep the existing
`test_ask_concatenates_streamed_text_and_scopes_cwd` test as-is for now — it moves to
testing `ask()` still calling through correctly in Step 5's rewrite):

```python
from claude_agent_sdk import (
    AssistantMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from coderag_mcp.orchestrator.ask import ask_stream


async def _scripted_query_stream(*, prompt, options):
    assert options.include_partial_messages is True
    yield AssistantMessage(
        content=[ThinkingBlock(thinking="Let me check the code.", signature="sig")],
        model="test",
    )
    yield AssistantMessage(
        content=[ToolUseBlock(id="toolu_1", name="Glob", input={"pattern": "*.py"})],
        model="test",
    )
    yield UserMessage(content=[ToolResultBlock(tool_use_id="toolu_1", content="main.py")])
    yield StreamEvent(
        uuid="u1", session_id="s1",
        event={"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
    )
    yield StreamEvent(
        uuid="u2", session_id="s1",
        event={"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Auth is "}},
    )
    yield StreamEvent(
        uuid="u3", session_id="s1",
        event={"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "in main.py."}},
    )
    yield StreamEvent(
        uuid="u4", session_id="s1",
        event={"type": "content_block_stop", "index": 0},
    )
    yield AssistantMessage(content=[TextBlock(text="Auth is in main.py.")], model="test")


@pytest.mark.asyncio
async def test_ask_stream_yields_one_event_per_block(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_scripted_query_stream),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="how does auth work?")
        ]

    assert events == [
        {"type": "reasoning", "text": "Let me check the code."},
        {"type": "tool_call", "tool": "Glob", "input": {"pattern": "*.py"}},
        {"type": "tool_result", "tool_use_id": "toolu_1", "output_preview": "main.py"},
        {"type": "answer_token", "text": "Auth is "},
        {"type": "answer_token", "text": "in main.py."},
        {"type": "done"},
    ]


@pytest.mark.asyncio
async def test_ask_stream_truncates_long_tool_results(tmp_path):
    conn = MagicMock()
    long_content = "x" * 500

    async def _one_tool_result(*, prompt, options):
        yield AssistantMessage(
            content=[ToolUseBlock(id="toolu_1", name="Read", input={"file_path": "big.py"})],
            model="test",
        )
        yield UserMessage(content=[ToolResultBlock(tool_use_id="toolu_1", content=long_content)])

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_one_tool_result),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="?")
        ]

    tool_result_event = next(e for e in events if e["type"] == "tool_result")
    assert len(tool_result_event["output_preview"]) < 500
    assert tool_result_event["output_preview"].endswith("... (truncated)")


@pytest.mark.asyncio
async def test_ask_stream_raises_timeout_error_if_query_never_completes(tmp_path):
    conn = MagicMock()

    async def _hanging_query_stream(*, prompt, options):
        await asyncio.sleep(10)
        yield  # pragma: no cover - unreachable

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_hanging_query_stream),
    ):
        with pytest.raises(TimeoutError):
            async for _event in ask_stream(
                conn, repo_id=1, repo_url="https://github.com/a/b", question="?", timeout_s=0.05
            ):
                pass
```

Check the top of `tests/orchestrator/test_ask.py` already imports `asyncio`, `pytest`,
`MagicMock`, `patch` (it does, from earlier tasks) — add the new `claude_agent_sdk`
imports above alongside the existing `AssistantMessage, SystemMessage, TextBlock`
import line.

- [x] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py -v`
Expected: FAIL (`ImportError: cannot import name 'ask_stream'`)

- [x] **Step 3: Write `ask_stream()` and refactor `ask()` into a wrapper**

Replace `coderag_mcp/orchestrator/ask.py` entirely:

```python
"""Runs the single-agent orchestrator behind ask_stream() and ask()."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    StreamEvent,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from coderag_mcp.indexing import clone
from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT
from coderag_mcp.orchestrator.tools import build_search_server

logger = logging.getLogger(__name__)

_PREVIEW_LIMIT = 400


def _preview(content: str | list[dict] | None) -> str:
    """Render a ToolResultBlock's content as a short, truncated preview string.

    content is str for most tools (Read, Glob, Grep, search_code all return plain
    text), but the SDK's type allows a list of content-block dicts too - handle both
    rather than assuming, since ToolResultBlock.content's type hint permits either.
    """
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    else:
        text = "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    if len(text) > _PREVIEW_LIMIT:
        return text[:_PREVIEW_LIMIT] + "... (truncated)"
    return text


async def ask_stream(
    conn: sqlite3.Connection,
    repo_id: int,
    repo_url: str,
    question: str,
    *,
    timeout_s: float = 180.0,
) -> AsyncIterator[dict[str, Any]]:
    """Run the orchestrator, yielding a structured event per tool call, tool result,
    reasoning block, and answer token as they arrive - the single source of truth
    for the Claude Agent SDK interaction. ask() is a thin wrapper over this.

    Does not catch and convert exceptions into error events itself - logs and
    re-raises exactly like the pre-streaming ask() implementation did (e.g. on
    timeout), same as api/ask_route.py's existing IndexingError/Exception handling
    pattern. Converting an exception into a safe client-facing message is the
    caller's job (the /ask/stream endpoint), not this function's.
    """
    search_server = build_search_server(conn, repo_id)

    repo_dir = await asyncio.to_thread(clone.clone_repo, repo_url, allow_local_paths=False)
    start = time.monotonic()
    logger.info(
        "orchestrator query starting",
        extra={"repo_url": repo_url, "question_length": len(question)},
    )
    try:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            allowed_tools=["mcp__search__search_code", "Read", "Grep", "Glob"],
            mcp_servers={"search": search_server},
            include_partial_messages=True,
        )

        # Tracks each currently-open content block's type by index, populated from
        # StreamEvent "content_block_start" events. Only "text" blocks stream
        # token-by-token via content_block_delta/text_delta - tool_use and thinking
        # blocks are reported as whole units from AssistantMessage/UserMessage below,
        # not from raw deltas, so this dict exists solely to know which deltas are
        # real answer text.
        block_types: dict[int, str] = {}

        try:
            async with asyncio.timeout(timeout_s):
                async for message in query(prompt=question, options=options):
                    if isinstance(message, StreamEvent):
                        event = message.event
                        event_type = event.get("type")
                        index = event.get("index")
                        if event_type == "content_block_start":
                            block = event.get("content_block") or {}
                            if index is not None:
                                block_types[index] = block.get("type")
                        elif event_type == "content_block_delta":
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta" and block_types.get(index) == "text":
                                yield {"type": "answer_token", "text": delta.get("text", "")}
                        elif event_type == "content_block_stop":
                            block_types.pop(index, None)
                        continue

                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, ThinkingBlock):
                                yield {"type": "reasoning", "text": block.thinking}
                            elif isinstance(block, ToolUseBlock):
                                yield {"type": "tool_call", "tool": block.name, "input": block.input}
                        continue

                    if isinstance(message, UserMessage):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                yield {
                                    "type": "tool_result",
                                    "tool_use_id": block.tool_use_id,
                                    "output_preview": _preview(block.content),
                                }
                        continue
        except TimeoutError:
            logger.error(
                "orchestrator query timed out after %.0fs",
                timeout_s,
                extra={"repo_url": repo_url, "timeout_s": timeout_s},
            )
            raise

        logger.info(
            "orchestrator query completed",
            extra={"repo_url": repo_url, "duration_s": time.monotonic() - start},
        )
        yield {"type": "done"}
    finally:
        await asyncio.to_thread(clone.cleanup_clone, repo_dir)


async def ask(
    conn: sqlite3.Connection,
    repo_id: int,
    repo_url: str,
    question: str,
    *,
    timeout_s: float = 180.0,
) -> str:
    """Thin wrapper over ask_stream(): concatenates the answer_token events into
    the final answer string. Used by POST /ask and the ask_repo MCP tool, both of
    which want only the final text. Any exception ask_stream() raises (e.g.
    TimeoutError) propagates through this unchanged - same external contract as
    before this refactor."""
    answer_parts: list[str] = []
    async for event in ask_stream(conn, repo_id, repo_url, question, timeout_s=timeout_s):
        if event["type"] == "answer_token":
            answer_parts.append(event["text"])
    return "".join(answer_parts)
```

- [x] **Step 4: Run the new tests to verify they pass**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py -v`
Expected: the 3 new `ask_stream` tests PASS. The existing
`test_ask_concatenates_streamed_text_and_scopes_cwd` test (unmodified) should also
still PASS at this point, since `ask()`'s external behavior is unchanged — confirm
this, since it's the proof this refactor didn't break `/ask`/`ask_repo`. If it fails,
do not change the test — the refactor has a real behavior regression, fix
`ask_stream()`/`ask()` instead.

- [x] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (88 + 3 new = 91)

- [x] **Step 6: Commit**

```bash
git add coderag_mcp/orchestrator/ask.py tests/orchestrator/test_ask.py
git commit -m "feat: add ask_stream() as the streaming orchestrator core, ask() as a thin wrapper"
```

---

### Task 2: `POST /ask/stream` — the SSE endpoint

**Files:**
- Create: `coderag_mcp/api/ask_stream_route.py`
- Modify: `coderag_mcp/api/main.py`
- Modify: `coderag_mcp/store/chunks.py`
- Test: `tests/api/test_ask_stream_route.py`

**Interfaces:**
- Consumes: `ask_stream` (Task 1, `orchestrator/ask.py`), `index_and_store_repo_async`
  and `run_db_sync` (existing, `orchestrator/indexing_service.py` /
  `store/db.py`), `require_api_key` and `get_db_conn` (existing, `api/auth.py` /
  `api/deps.py`), `repos.get_repo_id_by_url` (existing, `store/repos.py`).
- Produces: `count_chunks(conn: sqlite3.Connection, repo_id: int) -> int` in
  `coderag_mcp/store/chunks.py` (a small addition alongside the existing
  `insert_chunks`/`search_chunks`, needed for the `indexing_done` event's
  `chunk_count` field — no later task consumes it). The `POST /ask/stream` route
  itself is the endpoint, not a Python interface anything else imports.

- [x] **Step 1: Add `count_chunks` to `store/chunks.py`**

Edit `coderag_mcp/store/chunks.py`, adding this function after `search_chunks`:

```python
def count_chunks(conn: sqlite3.Connection, repo_id: int) -> int:
    """Number of chunks stored for repo_id - used to report indexing progress."""
    row = conn.execute("SELECT COUNT(*) FROM chunks WHERE repo_id = ?", (repo_id,)).fetchone()
    return row[0]
```

- [x] **Step 2: Write the failing test for `count_chunks`**

Add to `tests/store/test_chunks.py`:

```python
def test_count_chunks_returns_the_number_of_stored_chunks(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    repo_id = create_repo(conn, "https://github.com/a/b")

    assert count_chunks(conn, repo_id) == 0

    insert_chunks(conn, repo_id, [_chunk("a"), _chunk("b")], [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])

    assert count_chunks(conn, repo_id) == 2
```

Add `count_chunks` to the existing `from coderag_mcp.store.chunks import insert_chunks,
search_chunks` import line at the top of the file (check its exact current form
first).

- [x] **Step 3: Run the test to verify it fails, then passes**

Run: `./.venv/bin/pytest tests/store/test_chunks.py -v`
Expected: FAIL first (`ImportError`), then PASS after Step 1's addition (re-run to
confirm).

- [x] **Step 4: Write `coderag_mcp/api/ask_stream_route.py`**

```python
"""POST /ask/stream: the same job as POST /ask, but streams the orchestrator's
live progress (indexing, tool calls, tool results, reasoning, and the answer
token-by-token) as Server-Sent Events instead of waiting for a final answer."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from coderag_mcp.api.auth import require_api_key
from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.schemas import AskRequest
from coderag_mcp.indexing.models import IndexingError
from coderag_mcp.orchestrator.ask import ask_stream
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo_async
from coderag_mcp.store import repos as repo_store
from coderag_mcp.store.chunks import count_chunks
from coderag_mcp.store.db import run_db_sync

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream_events(conn: sqlite3.Connection, request: AskRequest) -> AsyncIterator[str]:
    try:
        existing_id = await run_db_sync(repo_store.get_repo_id_by_url, conn, request.repo_url)

        if existing_id is None:
            yield _sse({"type": "indexing_start", "repo_url": request.repo_url})
            start = time.monotonic()
            try:
                repo_id = await index_and_store_repo_async(conn, request.repo_url)
            except IndexingError as exc:
                yield _sse({"type": "error", "message": str(exc)})
                return
            except Exception:  # noqa: BLE001 - e.g. Voyage embedding failures
                logger.exception("indexing failed", extra={"repo_url": request.repo_url})
                yield _sse({"type": "error", "message": "Could not index the repository."})
                return
            chunk_count = await run_db_sync(count_chunks, conn, repo_id)
            yield _sse({
                "type": "indexing_done",
                "chunk_count": chunk_count,
                "duration_s": time.monotonic() - start,
            })
        else:
            repo_id = existing_id

        try:
            async for event in ask_stream(conn, repo_id, request.repo_url, request.question):
                yield _sse(event)
        except IndexingError as exc:
            # ask_stream() re-clones the repo on every call; this can fail with the
            # same errors as the initial index even on a cache hit.
            yield _sse({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001 - any other orchestrator/subagent failure
            logger.exception("ask_stream failed", extra={"repo_url": request.repo_url})
            yield _sse({"type": "error", "message": "Could not answer the question."})
    except Exception:  # noqa: BLE001 - defensive: never leave the SSE connection hanging
        logger.exception("unexpected failure in /ask/stream", extra={"repo_url": request.repo_url})
        yield _sse({"type": "error", "message": "Something went wrong."})


@router.post("/ask/stream", dependencies=[Depends(require_api_key)])
async def ask_stream_endpoint(
    request: AskRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> StreamingResponse:
    return StreamingResponse(_stream_events(conn, request), media_type="text/event-stream")
```

- [x] **Step 5: Wire the router into `api/main.py`**

Edit `coderag_mcp/api/main.py`. Add the import:

```python
from coderag_mcp.api.ask_stream_route import router as ask_stream_router
```

Find where `app.include_router(ask_router)` is called inside `create_app()` and add
right after it:

```python
    app.include_router(ask_router)
    app.include_router(ask_stream_router)
```

- [x] **Step 6: Write the end-to-end test**

Create `tests/api/test_ask_stream_route.py`:

```python
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
```

- [x] **Step 7: Run the new tests**

Run: `./.venv/bin/pytest tests/api/test_ask_stream_route.py -v`
Expected: PASS

- [x] **Step 8: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (91 + 1 [count_chunks] + 4 [ask_stream_route] = 96)

- [x] **Step 9: Commit**

```bash
git add coderag_mcp/api/ask_stream_route.py coderag_mcp/api/main.py coderag_mcp/store/chunks.py \
  tests/api/test_ask_stream_route.py tests/store/test_chunks.py
git commit -m "feat: add POST /ask/stream SSE endpoint streaming live orchestrator progress"
```

---

## Final check

After Task 2, run `./.venv/bin/pytest -v` once more from the repo root and confirm
the full suite (96/96) passes before moving to
`superpowers:finishing-a-development-branch`.
