"""Runs the single-agent orchestrator behind ask()."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from coderag_mcp.indexing import clone
from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT
from coderag_mcp.orchestrator.tools import build_search_server

logger = logging.getLogger(__name__)


async def ask(
    conn: sqlite3.Connection,
    repo_id: int,
    repo_url: str,
    question: str,
    *,
    timeout_s: float = 180.0,
) -> str:
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
        )

        answer_parts: list[str] = []
        try:
            async with asyncio.timeout(timeout_s):
                async for message in query(prompt=question, options=options):
                    if not isinstance(message, AssistantMessage):
                        continue
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            answer_parts.append(block.text)
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
        return "".join(answer_parts)
    finally:
        await asyncio.to_thread(clone.cleanup_clone, repo_dir)
