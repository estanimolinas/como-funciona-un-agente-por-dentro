"""Runs the single-agent orchestrator behind ask()."""
from __future__ import annotations

import asyncio
import sqlite3

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from coderag_mcp.indexing import clone
from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT
from coderag_mcp.orchestrator.tools import build_search_server


async def ask(conn: sqlite3.Connection, repo_id: int, repo_url: str, question: str) -> str:
    search_server = build_search_server(conn, repo_id)

    repo_dir = await asyncio.to_thread(clone.clone_repo, repo_url, allow_local_paths=False)
    try:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            allowed_tools=["mcp__search__search_code", "Read", "Grep", "Glob"],
            mcp_servers={"search": search_server},
        )

        answer_parts: list[str] = []
        async for message in query(prompt=question, options=options):
            if not isinstance(message, AssistantMessage):
                continue
            for block in message.content:
                if isinstance(block, TextBlock):
                    answer_parts.append(block.text)

        return "".join(answer_parts)
    finally:
        await asyncio.to_thread(clone.cleanup_clone, repo_dir)
