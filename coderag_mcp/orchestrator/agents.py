"""Subagent definitions and the on-demand clone used by code-explorer."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from claude_agent_sdk import AgentDefinition

from coderag_mcp.indexing import clone


@contextmanager
def fresh_clone(repo_url: str) -> Iterator[Path]:
    """Clone repo_url into a fresh temp dir for this request; always cleaned up after."""
    repo_dir = clone.clone_repo(repo_url, allow_local_paths=False)
    try:
        yield repo_dir
    finally:
        clone.cleanup_clone(repo_dir)


RAG_SEARCH = AgentDefinition(
    description=(
        "Answers conceptual questions about the repo using semantic search over "
        "indexed code chunks. Use for 'how does X work' / 'where is X handled' style "
        "questions where similarity to the question's meaning is what matters."
    ),
    prompt=(
        "You are a semantic code search specialist. Use the search_code tool to find "
        "relevant chunks, then explain what they do, citing file:line for each chunk "
        "you reference."
    ),
    tools=["mcp__search__search_code"],
)

CODE_EXPLORER = AgentDefinition(
    description=(
        "Explores the actual cloned repository files with exact search (grep/glob) "
        "and reads real file content. Use for structural or exact-location questions "
        "where current file:line accuracy matters more than semantic similarity."
    ),
    prompt=(
        "You are a code exploration specialist. Use Grep and Glob to locate exact "
        "code, then Read to inspect it. Always report file paths relative to the repo "
        "root and exact line numbers from what you actually read - never guess line "
        "numbers or rely on memory of similar codebases."
    ),
    tools=["Read", "Grep", "Glob"],
)
