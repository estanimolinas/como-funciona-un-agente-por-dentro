import asyncio
from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from coderag_mcp.orchestrator.ask import ask, ask_stream


async def _fake_query_stream(*, prompt, options):
    assert prompt == "how does auth work?"
    assert options.allowed_tools == ["mcp__search__search_code", "Read", "Grep", "Glob"]
    assert options.agents is None
    # A non-AssistantMessage should be ignored, not concatenated into the answer.
    yield SystemMessage(subtype="subagent_start", data={})
    yield AssistantMessage(content=[TextBlock(text="Auth is handled in ")], model="test")
    yield AssistantMessage(content=[TextBlock(text="auth.py:10-20.")], model="test")


@pytest.mark.asyncio
async def test_ask_concatenates_streamed_text_and_scopes_cwd(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path) as mock_clone,
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone") as mock_cleanup,
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=5),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_fake_query_stream),
    ):
        answer = await ask(conn, repo_id=1, repo_url="https://github.com/a/b", question="how does auth work?")

    assert answer == "Auth is handled in auth.py:10-20."
    mock_clone.assert_called_once_with("https://github.com/a/b", allow_local_paths=False)
    mock_cleanup.assert_called_once_with(tmp_path)


async def _hanging_query_stream(*, prompt, options):
    # Never yields - simulates a stuck claude CLI subprocess.
    await asyncio.sleep(10)
    yield  # pragma: no cover - unreachable, makes this a generator function


@pytest.mark.asyncio
async def test_ask_raises_timeout_error_if_query_never_completes(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=5),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_hanging_query_stream),
    ):
        with pytest.raises(TimeoutError):
            await ask(
                conn,
                repo_id=1,
                repo_url="https://github.com/a/b",
                question="how does auth work?",
                timeout_s=0.05,
            )


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
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=5),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_scripted_query_stream),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="how does auth work?")
        ]

    assert events == [
        {"type": "reasoning", "text": "Let me check the code."},
        {"type": "tool_call", "tool": "Glob", "input": {"pattern": "*.py"}},
        {
            "type": "tool_result",
            "tool": "Glob",
            "tool_use_id": "toolu_1",
            "output_preview": "main.py",
            "is_error": None,
        },
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
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=5),
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
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=5),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_hanging_query_stream),
    ):
        with pytest.raises(TimeoutError):
            async for _event in ask_stream(
                conn, repo_id=1, repo_url="https://github.com/a/b", question="?", timeout_s=0.05
            ):
                pass


async def _reasoning_capturing_query_stream(*, prompt, options):
    # Captures the system prompt actually passed to query() so the test can
    # assert on the appended no-index note, then yields a trivial answer.
    _reasoning_capturing_query_stream.captured_system_prompt = options.system_prompt
    yield AssistantMessage(content=[TextBlock(text="No index available here.")], model="test")


@pytest.mark.asyncio
async def test_ask_stream_yields_no_semantic_index_event_when_zero_chunks(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=0) as mock_count,
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_reasoning_capturing_query_stream),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="q")
        ]

    mock_count.assert_called_once_with(conn, 1)
    assert events[0] == {
        "type": "no_semantic_index",
        "message": (
            "This repository has no indexed code (unsupported language, or an "
            "empty/non-code repo) — answering by exploring files directly instead "
            "of semantic search."
        ),
    }
    assert "no indexed code" in _reasoning_capturing_query_stream.captured_system_prompt
    assert "search_code" in _reasoning_capturing_query_stream.captured_system_prompt


@pytest.mark.asyncio
async def test_ask_stream_omits_no_semantic_index_event_when_chunks_exist(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=42),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_reasoning_capturing_query_stream),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="q")
        ]

    assert all(event["type"] != "no_semantic_index" for event in events)
    assert "no indexed code" not in _reasoning_capturing_query_stream.captured_system_prompt
