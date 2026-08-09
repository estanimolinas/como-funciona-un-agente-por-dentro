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

**Plans 1 and 2 of several — done, merged to `main`, 30/30 tests
passing.** See `docs/superpowers/plans/2026-08-08-coderag-mcp-scaffold-and-spike.md`
and `docs/superpowers/plans/2026-08-08-indexing-pipeline.md` (all steps
checked off) for exactly what was built and how each was reviewed.

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
- `coderag_mcp/indexing/` (Plan 2 — clone → tree-sitter → chunk):
  - `models.py` — `Chunk` dataclass and the `IndexingError` exception
    hierarchy (`InvalidRepoURLError`, `CloneTimeoutError`,
    `RepoTooLargeError`, `TooManyFilesError`, `PipelineTimeoutError`).
  - `clone.py` — `clone_repo(url, *, allow_local_paths=False) -> Path` and
    `cleanup_clone(cloned_path) -> None`. Validates host allowlist
    (`github.com`/`gitlab.com`), rejects SCP-style git URLs, `file://`
    URLs, and dash-prefixed URLs (git argument-injection defense — always
    passes `--` before the URL to `git clone` too). `allow_local_paths` is
    an explicit opt-in used only by tests against the local fixture repo —
    keep it `False` by default when this is wired behind an HTTP/MCP
    endpoint later, so a caller can never get local-file disclosure through
    the indexing path.
  - `chunker.py` — `chunk_file(path, repo_url, file_path) -> list[Chunk]`.
    tree-sitter-python parse; extracts top-level functions, classes, and
    each method inside a class as its own chunk. Unwraps
    `decorated_definition` nodes so `@staticmethod`/`@property`/etc. don't
    get silently dropped. Any per-file failure (syntax error, non-UTF-8
    encoding, anything else) is caught internally, logged, and returns
    `[]` for that file — never raises.
  - `pipeline.py` — `index_repo(repo_url, *, allow_local_paths=False) ->
    list[Chunk]`, the sole public entry point for this plan: clone → walk
    `.py` files (capped at `MAX_FILE_COUNT=500`) → chunk each (wrapped in
    its own defensive try/except as a second safety net) → clean up via
    `clone.cleanup_clone`. No HTTP endpoint, no DB, no embeddings yet —
    Plan 3 calls this function directly.
  - Tests in `tests/indexing/` run against a real local git repo built by
    the `fixture_repo` fixture in `conftest.py` (`git init` + a commit) —
    zero network dependency.

  **Two rounds of security hardening happened during Plan 2's review loop,
  beyond what the original plan text specified — don't reintroduce these:**
  the host-allowlist bypass via SCP-style URLs (`user@host:path` and bare
  `host:path`, git's own remote syntax) and unconditional `file://`
  pass-through; and a git argument-injection bypass via dash-prefixed URLs
  reaching `git clone` in option position (fixed with both an app-level
  reject-leading-dash check and a `--` separator before the URL,
  belt-and-suspenders). Both were caught by the review loop, not written
  correctly the first time — a sign the review discipline is doing its job,
  not that the code is now bulletproof against every future finding.

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
via writing-plans + subagent-driven-development, same as Plans 1-2):

1. ~~MCP server spike~~ — done (Plan 1).
2. ~~Indexing pipeline~~ — done (Plan 2). See
   `docs/superpowers/specs/2026-08-08-indexing-pipeline-design.md` for the
   design and `docs/superpowers/plans/2026-08-08-indexing-pipeline.md` for
   the implementation plan (all 5 tasks + the final-review fix wave
   checked off).
3. Embeddings (Voyage `voyage-code-3`) + Postgres/pgvector store (HNSW
   index) + Alembic migrations. Recommended distance metric: cosine
   similarity (pgvector `<=>` operator, HNSW index with
   `vector_cosine_ops`) — `voyage-code-3` embeddings are meant to be
   compared this way, not with Euclidean distance. Consumes
   `coderag_mcp.indexing.pipeline.index_repo()`'s `list[Chunk]` output
   directly.
4. RAG endpoint: retrieval + Claude-generated answer with file:line
   citations.
5. Wire the real MCP tools (`index_repo`, `search_code`, `ask_repo`) onto
   the `mcp` object in `mcp_server/server.py` — the mounting/lifespan code
   in `api/main.py` should not need changes for this. **When wiring
   `index_repo` behind HTTP/MCP, do not pass `allow_local_paths=True`** —
   that flag exists solely for Plan 2's own tests against a local fixture
   repo; a real endpoint must only ever accept `github.com`/`gitlab.com`
   URLs.
6. Auth (API key), remaining production-readiness pieces from the spec.
   This is also the natural point to promote Plan 2's hardcoded indexing
   constants (`ALLOWED_HOSTS`, `MAX_REPO_SIZE_MB`, `CLONE_TIMEOUT_S`,
   `MAX_FILE_COUNT`, `PIPELINE_TIMEOUT_S`) to `pydantic-settings`, and to
   revisit the pre-clone size mitigation (currently a
   `--filter=blob:limit=<n>` partial-clone flag plus a post-clone aggregate
   check — no true streaming/disk-quota enforcement yet).
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
