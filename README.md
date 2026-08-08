# CodeRAG-MCP

Code-aware RAG backend: indexes public repositories with AST-aware chunking
(tree-sitter), stores embeddings in Postgres/pgvector, and answers questions
about the code with file:line citations. Served both as a REST API and as
an MCP server (Streamable HTTP), so it can be queried directly or plugged
into any MCP client (Claude Desktop, Claude.ai connectors, etc.).

**Status:** early scaffold — see the full design doc for architecture,
decisions, and roadmap.

## Inspiration

Design patterns in this project are inspired by
[nanoLoop](https://github.com/ismaelfaro/nanoLoop), an autonomous
engineering harness: the default-deny/explicit-allowlist approach to
security, the `pending → active → done/blocked`-style job state machine,
and the env-var-driven client factory pattern. No code is shared — nanoLoop
is a LangChain/DeepAgents agent harness, this is a RAG/MCP service, with
different stacks.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

## Run

```bash
./.venv/bin/uvicorn coderag_mcp.api.main:app --reload
```

## Test

```bash
./.venv/bin/pytest -v
```
