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
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from coderag_mcp.indexing import clone
from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT
from coderag_mcp.orchestrator.tools import build_search_server
from coderag_mcp.store.chunks import count_chunks
from coderag_mcp.store.db import run_db_sync

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

    chunk_count = await run_db_sync(count_chunks, conn, repo_id)
    has_semantic_index = chunk_count > 0
    if not has_semantic_index:
        yield {
            "type": "no_semantic_index",
            "message": (
                "Este repositorio no tiene código indexado (idioma no soportado, o un "
                "repositorio vacío/sin código) — respondiendo mediante exploración "
                "directa de archivos en lugar de búsqueda semántica."
            ),
        }

    repo_dir = await asyncio.to_thread(clone.clone_repo, repo_url, allow_local_paths=False)
    start = time.monotonic()
    logger.info(
        "orchestrator query starting",
        extra={"repo_url": repo_url, "question_length": len(question)},
    )
    try:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            system_prompt=(
                ORCHESTRATOR_SYSTEM_PROMPT
                if has_semantic_index
                else ORCHESTRATOR_SYSTEM_PROMPT
                + "\n\nNote: this repository has no indexed code (unsupported "
                "language, or an empty/non-code repo) — search_code will return no "
                "useful results here. Rely on Read, Grep, and Glob instead."
            ),
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

        # Maps each ToolUseBlock's id to its tool name, so a later ToolResultBlock
        # (which only carries tool_use_id) can be enriched with the tool name that
        # produced it - a consumer of the "tool_result" event otherwise has no way
        # to correlate it back to which tool ran.
        tool_names_by_id: dict[str, str] = {}

        # True once at least one answer_token has been emitted from a StreamEvent
        # text_delta. When the SDK streams partial messages (the normal case, since
        # include_partial_messages=True above), answer text arrives token-by-token
        # via StreamEvent and the final AssistantMessage's TextBlock just repeats the
        # same text as one whole block - skip it there to avoid double-emitting. If
        # no deltas ever arrived for this query (e.g. a caller/test that doesn't
        # simulate partial-message streaming), fall back to emitting the
        # AssistantMessage's TextBlock text directly so answer text is never lost.
        streamed_any_text = False

        try:
            # NOTE: this generator can be suspended (at a `yield` below) inside a
            # caller's frame - e.g. while StreamingResponse is writing a chunk to a
            # socket - at the moment this timeout fires. In that rare case,
            # asyncio.CancelledError may surface directly to the consumer instead of
            # being converted to TimeoutError by this `async with` block's
            # __aexit__, bypassing the `except TimeoutError` handler below. Most wall
            # time is spent awaiting inside query() itself, where the conversion
            # works correctly, so this is a low-probability edge case, not a fix.
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
                                streamed_any_text = True
                                yield {"type": "answer_token", "text": delta.get("text", "")}
                        elif event_type == "content_block_stop":
                            block_types.pop(index, None)
                        continue

                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, ThinkingBlock):
                                yield {"type": "reasoning", "text": block.thinking}
                            elif isinstance(block, ToolUseBlock):
                                tool_names_by_id[block.id] = block.name
                                yield {"type": "tool_call", "tool": block.name, "input": block.input}
                            elif isinstance(block, TextBlock) and not streamed_any_text:
                                yield {"type": "answer_token", "text": block.text}
                        continue

                    if isinstance(message, UserMessage):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                yield {
                                    "type": "tool_result",
                                    "tool": tool_names_by_id.get(block.tool_use_id),
                                    "tool_use_id": block.tool_use_id,
                                    "output_preview": _preview(block.content),
                                    "is_error": block.is_error,
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
