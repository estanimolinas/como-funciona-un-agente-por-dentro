# CodeRAG-MCP — context for a fresh Claude session

Read this before doing anything else in this repo.

## What this is

A portfolio backend project: code-aware RAG over public git repositories,
served both as a REST API and as an MCP server (Streamable HTTP transport).
Indexes a repo with AST-aware chunking (tree-sitter, function/class-level,
not naive line-splitting), embeds chunks with Voyage AI's `voyage-code-3`,
stores vectors in Postgres/pgvector, and answers questions with file:line
citations via Claude.

Target audience: ML/AI engineers reviewing a GitHub portfolio. The point is
to demonstrate real RAG-pipeline judgment and current protocol fluency
(MCP), not to ship every possible feature — scope is deliberately trimmed
to what a solo developer can actually finish and defend in an interview.

**Full design doc (read this for the "why" behind every decision):**
`docs/superpowers/specs/2026-08-08-coderag-mcp-backend-design.md`

That doc covers: architecture, component responsibilities, data flow,
security constraints (repo-clone allowlist/timeout/size caps), the
production-readiness pieces that are and aren't in v1, the build order, and
the explicit roadmap of what's deferred to v1.1 (RQ/Redis, multi-language,
rate limiting).

## Where this came from

Designed via a brainstorming session in a separate repo
([nanoLoop](https://github.com/ismaelfaro/nanoLoop), an unrelated agentic
harness project) using the Superpowers skill workflow
(brainstorming → writing-plans → subagent-driven-development). This repo's
`docs/superpowers/` holds a local copy of that spec and the first
implementation plan, so this repo is self-contained — you should not need
to look at the nanoLoop repo to continue this work.

**Design inspiration only, not code:** nanoLoop's default-deny/allowlist
security pattern, its `pending → active → done/blocked` job state machine,
and its env-var-driven client factory pattern all shaped choices here (see
the spec's "Why a new repo, not an extension of nanoLoop" section and the
README's "Inspiration" section). No code or dependencies are shared —
nanoLoop is a LangChain/DeepAgents harness; this is a plain FastAPI/MCP
service.

## Current status

**Plan 1 of several — done, merged to `main`, 3 commits, 2/2 tests
passing.** See `docs/superpowers/plans/2026-08-08-coderag-mcp-scaffold-and-spike.md`
(all steps checked off) for exactly what was built and how it was reviewed.

What exists right now:
- `coderag_mcp/api/main.py` — FastAPI app, `/health` endpoint, MCP server
  mounted at `/mcp`. Has a docstring explaining the SDK-version adaptation
  (see below) — read it before touching this file.
- `coderag_mcp/mcp_server/server.py` — the MCP server object (`mcp`), one
  dummy tool (`ping`) used only to prove the Streamable HTTP wiring works
  end-to-end. Real tools (`index_repo`, `search_code`, `ask_repo`) get added
  here in a later plan — the mounting/lifespan wiring in `api/main.py`
  should not need to change when that happens.
- `coderag_mcp/config.py` — typed settings (`pydantic-settings`). Has
  `public_host` (for the MCP transport's allowed-hosts config at deploy
  time) — everything else is still unwired, waiting on later plans.
- `tests/test_mcp_server.py` — real end-to-end test: spins up a real
  `uvicorn` server on a real socket, connects with a real MCP client,
  calls the `ping` tool. Not mocked. This is the pattern to follow for
  testing the real tools later — no shortcuts here, the whole point of
  this project's MCP layer is that it actually works against a real
  client.

**Important gotcha already paid for — don't rediscover it:** the `mcp`
Python SDK installed here is **2.0.0**, which has a completely different
API from what's commonly documented/expected (no `FastMCP`; the class is
`MCPServer` in `mcp.server.mcpserver`; different lifespan wiring via
`app.router.lifespan_context`; client import is `streamable_http_client`,
not `streamablehttp_client`). `pyproject.toml` pins `mcp>=2.0.0,<3.0.0` —
keep that upper bound, since an earlier version of this pin let a breaking
release in unnoticed. If you're adding new MCP-related code, look at how
`coderag_mcp/api/main.py` and `tests/test_mcp_server.py` already use the
SDK before assuming any online example or your own training knowledge is
current — they may describe the older `FastMCP`-based API.

## Known deferred items (not bugs, just not done yet)

- `/mcp` (no trailing slash) 307-redirects to `/mcp/` — the MCP client
  follows redirects automatically so it works, but document `/mcp/` as
  canonical if this becomes user-facing, and run uvicorn with
  `--proxy-headers` in production to avoid scheme-mangling behind a
  TLS-terminating proxy.
- `tests/test_mcp_server.py`'s server-thread teardown doesn't assert the
  thread actually stopped; `TEST_PORT` is hardcoded (8765) and would
  collide under parallel test execution (e.g. `pytest-xdist`).
- No `LICENSE` file, no CI yet.
- `get_settings()` has no `@lru_cache` — fine at current scale, revisit if
  it's called per-request somewhere later.

## What comes next

Per the design doc's Build Order, in this sequence (each gets its own plan
via writing-plans + subagent-driven-development, same as Plan 1):

1. ~~MCP server spike~~ — done (this is Plan 1).
2. Indexing pipeline: repo cloning (host allowlist, shallow clone,
   size/timeout caps — see spec's Security section for exact limits),
   tree-sitter parsing (Python only for v1), chunker (function/class-level
   + metadata).
3. Embeddings (Voyage `voyage-code-3`) + Postgres/pgvector store (HNSW
   index) + Alembic migrations.
4. RAG endpoint: retrieval + Claude-generated answer with file:line
   citations.
5. Wire the real MCP tools (`index_repo`, `search_code`, `ask_repo`) onto
   the `mcp` object in `mcp_server/server.py` — the mounting/lifespan code
   in `api/main.py` should not need changes for this.
6. Auth (API key), remaining production-readiness pieces from the spec.
7. Minimal React+Vite+TypeScript frontend (separate plan, deliberately
   deferred — this repo is backend-first).
8. Deploy (Render + Supabase + Vercel per the spec) + polish the README
   (architecture diagram, demo GIF, live URL, design-decisions section) +
   ADRs.

## How to work in this repo

- Python 3.11+, venv at `.venv/` (`./.venv/bin/pytest`, `./.venv/bin/pip`).
- `./.venv/bin/pytest -v` — run the test suite before and after any change.
- Follow the same workflow used to build this: brainstorm/clarify scope
  changes with the human partner first (the design doc is the source of
  truth — don't silently deviate from it), then `writing-plans` to produce
  a task-by-task plan, then `subagent-driven-development` to execute it
  with per-task review and a final whole-branch review. Don't skip the
  review loop — it's what caught the two real bugs (broken version pin,
  loopback-only MCP host) in Plan 1's final review.
- No LangChain, no DeepAgents, no OpenShell — those belong to nanoLoop, not
  here.
