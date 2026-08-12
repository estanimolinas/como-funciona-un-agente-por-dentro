# AgentTrace

Code-aware RAG backend: indexes public repositories with AST-aware chunking
(tree-sitter), embeds chunks with Voyage AI's `voyage-code-3`, and stores
them in SQLite with the `sqlite-vec` extension (cosine similarity). Answers
questions about the code, with file:line citations, via a Claude Agent SDK
single-agent orchestrator that combines semantic search with exact file
reading. Served both as a REST API (`POST /ask`) and as an MCP server
(Streamable HTTP, mounted at `/mcp/`), so it can be queried directly or
plugged into any MCP client (Claude Desktop, Claude.ai connectors, etc.).

**Status:** REST (`POST /ask`) and MCP (`index_repo`, `search_code`,
`ask_repo`) are both live end-to-end, behind optional API-key auth — see the
full design doc for architecture, decisions, and roadmap.

## Demo

[![AgentTrace demo](https://img.youtube.com/vi/g_o0UT6XCRw/maxresdefault.jpg)](https://youtu.be/g_o0UT6XCRw)

Live walkthrough of the local frontend: indexing a repo, the agent choosing
between semantic search and direct file exploration per question, and the
live two-column trace of that decision as it happens.

## How it works

1. **Index** — clone a public repo, parse `.py` files with tree-sitter,
   extract one chunk per top-level function/class/method (not naive
   line-splitting), embed each chunk with Voyage AI's `voyage-code-3`, and
   store the vectors in SQLite via the `sqlite-vec` extension. Idempotent by
   URL — a repo already indexed is a no-op.
2. **Ask** — a single Claude Agent SDK agent gets both a semantic search
   tool (`search_code`, over the indexed chunks) and direct file tools
   (`Read`/`Grep`/`Glob`, over the real cloned files) and picks per
   question which to use — conceptual/"how does X work" questions lean
   toward semantic search, exact-symbol/"what does file:line do" questions
   lean toward direct exploration.
3. **Trace** — every tool call, tool result, and answer token streams out
   as a structured event (`POST /ask/stream`), so a caller can watch which
   method the agent picked and why, not just get a final answer.

### Design decisions worth knowing

- **SQLite + `sqlite-vec` instead of Postgres/pgvector** — the original
  design doc specified Postgres; this was superseded early on since a
  single-file embedded vector store needs no separate DB service to run or
  deploy, at the cost of concurrent-write scaling headroom this project
  doesn't need.
- **One agent, not a dispatcher-plus-subagents architecture** — an earlier
  design had a top-level orchestrator dispatching to separate
  `rag-search`/`code-explorer` subagents via the Agent tool. Collapsed into
  a single agent given both tool families directly: dispatching added a
  token/latency round-trip for a decision the model can make itself.
- **Tool choice is a live decision, not a scripted pipeline** — this is
  deliberately not "always embed-search-then-generate." The agent decides
  per question, which is also why the demo's live trace exists: the point
  is to make that decision visible, not just the final answer.
- **Python-only chunking** — tree-sitter-python is the only chunker
  implemented; other languages fall back to direct file exploration
  (`Read`/`Grep`/`Glob`) with no semantic index, which the UI/agent are
  both told about explicitly rather than silently returning empty results.

## Inspiration

Design patterns in this project are inspired by
[nanoLoop](https://github.com/ismaelfaro/nanoLoop), an autonomous
engineering harness: the default-deny/explicit-allowlist approach to
security, the `pending → active → done/blocked`-style job state machine,
and the env-var-driven client factory pattern. No code is shared — nanoLoop
is a LangChain/DeepAgents agent harness, this is a RAG/MCP service, with
different stacks.

## Quickstart

Requires the `claude` CLI installed and authenticated
(`npm i -g @anthropic-ai/claude-code && claude login`), or `ANTHROPIC_API_KEY`
exported — `POST /ask` and the `ask_repo` MCP tool run through the Claude
Agent SDK, which drives this CLI as a subprocess. Without one of the two, a
first `curl /ask` will fail.

```bash
git clone https://github.com/estanimolinas/como-funciona-un-agente-por-dentro.git
cd como-funciona-un-agente-por-dentro
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"

cp .env.example .env
# edit .env: set VOYAGE_API_KEY (see .env.example for where to get one)

./.venv/bin/uvicorn coderag_mcp.api.main:app --reload
```

The server refuses to start if `VOYAGE_API_KEY` is missing, with a message
telling you what's wrong - see `coderag_mcp/config.py`'s `validate_settings`.

Ask it a question about any public GitHub/GitLab repo (indexes it on first
use):

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/pypa/sampleproject", "question": "What does this project do, and where is the package version defined?"}'
```

`POST /ask/stream` takes the same request body and returns the same answer,
but as Server-Sent Events (`data: <json>\n\n`) streaming the orchestrator's
live progress as it happens — indexing status, each tool call and result,
and the answer token-by-token — instead of waiting for one final response.

All other settings (`CODERAG_PUBLIC_HOST`, `CODERAG_SQLITE_DB_PATH`,
`CODERAG_ALLOWED_HOSTS`, etc.) are optional and have sensible defaults — see
`coderag_mcp/config.py`. Note the `CODERAG_` prefix: every setting except
`VOYAGE_API_KEY` is only read from its `CODERAG_`-prefixed env var name, so a
generic env var like `ALLOWED_HOSTS` (common on PaaS platforms) can't
accidentally override it.

## Frontend (optional)

A local-only React frontend showing a live view of the orchestrator's
tool calls and streamed answer as it works — see
[`frontend/README.md`](frontend/README.md) for setup. Not required to use
the REST or MCP API directly.

## Auth

If `CODERAG_API_KEY` is set, `/ask`, `/ask/stream`, and `/mcp` all require
an `X-API-Key` header matching it — requests without it (or with the wrong
value) get a 401. If `CODERAG_API_KEY` is unset (the default), auth is
disabled and any request is accepted.

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-chosen-secret" \
  -d '{"repo_url": "https://github.com/owner/repo", "question": "How does X work?"}'
```

## MCP server

An MCP server (Streamable HTTP transport) is mounted at `/mcp/` on the same
running app (`/mcp` without the trailing slash 307-redirects to `/mcp/`;
MCP clients follow redirects automatically), subject to the same
`X-API-Key` requirement described above. It exposes:

- `ping` — trivial health check.
- `index_repo(repo_url)` — clone, chunk, embed, and store a public
  GitHub/GitLab repo (idempotent by URL; a no-op if already indexed).
- `search_code(repo_url, query, top_k=5)` — semantic search over a repo's
  indexed code chunks, indexing it first if this is the first call.
- `ask_repo(repo_url, question)` — answer a question about a repo via the
  same single-agent orchestrator `POST /ask` uses, indexing it first if
  needed.

### Using it as an MCP server in Claude Code

With the server running (see Quickstart above):

```bash
claude mcp add --transport http coderag http://localhost:8000/mcp/
```

If `CODERAG_API_KEY` is set, pass it as a header:

```bash
claude mcp add --transport http coderag http://localhost:8000/mcp/ \
  --header "X-Api-Key: your-chosen-secret"
```

Verify it connected: `claude mcp list` should show `coderag` as `✔ Connected`.
Claude Code can now call `index_repo`, `search_code`, and `ask_repo` directly.

## Test

```bash
./.venv/bin/pytest -v
```
