"""Ties the two subagents together behind a single ask() call."""
from __future__ import annotations

import sqlite3

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from coderag_mcp.orchestrator.agents import CODE_EXPLORER, RAG_SEARCH, fresh_clone
from coderag_mcp.orchestrator.tools import build_search_server


async def ask(conn: sqlite3.Connection, repo_id: int, repo_url: str, question: str) -> str:
    search_server = build_search_server(conn, repo_id)

    with fresh_clone(repo_url) as repo_dir:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            allowed_tools=["Agent"],
            mcp_servers={"search": search_server},
            agents={"rag-search": RAG_SEARCH, "code-explorer": CODE_EXPLORER},
        )

        answer_parts: list[str] = []
        async for message in query(prompt=question, options=options):
            if not isinstance(message, AssistantMessage):
                continue
            for block in message.content:
                if isinstance(block, TextBlock):
                    answer_parts.append(block.text)

        return "".join(answer_parts)
