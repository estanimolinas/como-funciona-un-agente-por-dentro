"""The single-agent orchestrator's system prompt.

Previously this module also defined two AgentDefinitions (rag-search, code-explorer)
that a top-level orchestrator dispatched to via the Agent tool, plus a fresh_clone
context manager used only by that dispatch flow. That added a subagent-dispatch
round-trip (token + latency cost) on every question for a decision the model itself
can make directly, given both tool families up front - see
docs/superpowers/specs/2026-08-10-single-agent-mcp-tools-auth-design.md's "Bloque 2"
for the full rationale. orchestrator/ask.py now gives the single top-level agent
mcp__search__search_code plus Read/Grep/Glob directly, guided by this prompt, and
clones the repo itself (Task 4's asyncio.to_thread-offloaded clone.clone_repo call).
"""
from __future__ import annotations

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are a code question-answering assistant with two ways to find information "
    "in this repository:\n"
    "- search_code: semantic search over pre-indexed code chunks. Use this for "
    "conceptual questions ('how does X work', 'where is X handled') where matching "
    "the meaning of the question matters more than exact wording.\n"
    "- Read, Grep, Glob: exact search and file reading over the real, current "
    "repository files. Use this for structural or exact-location questions where "
    "precise, up-to-date file:line accuracy matters more than semantic similarity.\n"
    "Choose per question - don't default to only one. Always cite file:line for "
    "anything you reference."
)
