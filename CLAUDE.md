# CodeRAG-MCP — context for a fresh Claude session

Read this before doing anything else in this repo.

## What this is

A portfolio backend project: code-aware RAG over public git repositories,
served both as a REST API and as an MCP server (Streamable HTTP transport).
Indexes a repo with AST-aware chunking (tree-sitter, function/class-level,
not naive line-splitting), embeds chunks with Voyage AI's `voyage-code-3`,
stores vectors in SQLite/`sqlite-vec`, and answers questions with file:line
citations via a Claude Agent SDK orchestrator (`POST /ask`) that routes
between a semantic-search subagent and a code-exploration subagent.

**Architecture note:** the original design doc (linked below) specified
Postgres/pgvector and a single retrieval-then-generate RAG endpoint. That
was superseded before implementation by
`docs/superpowers/specs/2026-08-09-orchestrator-rag-architecture-design.md`
— SQLite+`sqlite-vec` instead of Postgres, and a dual-path orchestrator
(Claude Agent SDK, `rag-search` + `code-explorer` subagents) instead of a
single retrieval call. The design doc below is still correct for
architecture/security-constraints background; treat its store/RAG-endpoint
specifics as superseded by the orchestrator spec.

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

**Plans 1, 2, and the dual-path-orchestrator plan — done, merged to
`main`, 58/58 tests passing.** See
`docs/superpowers/plans/2026-08-08-coderag-mcp-scaffold-and-spike.md`,
`docs/superpowers/plans/2026-08-08-indexing-pipeline.md`, and
`docs/superpowers/plans/2026-08-09-dual-path-orchestrator.md` (all steps
checked off in the SDD ledger, though not in the plan files' own
checkboxes — the ledger is the authoritative record) for exactly what was
built and how each was reviewed. `POST /ask` is live end-to-end: index
(clone → chunk → embed → store) on first request, then the orchestrator
answers via `rag-search`/`code-explorer` subagents.

**In addition to the two Plan 2 hardening rounds below, the
dual-path-orchestrator plan's whole-branch review (7-angle multi-agent
pass) found and fixed 5 real correctness/robustness bugs** — worth
knowing about since they're the kind of thing a fresh session might
reintroduce:
- `embeddings/voyage.py`'s `embed_batch` was embedding search queries with
  `input_type="document"` (the corpus-side setting) instead of `"query"` —
  `voyage-code-3` is asymmetric, so this silently degraded retrieval
  quality with no error. Fixed with an `input_type` parameter, defaulting
  to `"document"`; `tools.py`'s `search_code` now passes `"query"`.
- `api/ask_route.py` only mapped `IndexingError` from the *initial* index
  call to 400; `ask()`'s always-on re-clone (see below) can raise the same
  `IndexingError`s, and Voyage/DB failures during indexing aren't
  `IndexingError` subclasses — both cases were escaping to an opaque
  502/500. Fixed with explicit `except IndexingError` + `except Exception`
  handling around both calls.
- `orchestrator/ask.py`'s answer extraction walked every streamed
  message's `content` via `getattr` and concatenated all text found,
  instead of isolating the final `AssistantMessage`/`TextBlock` text —
  fixed with `isinstance` checks.
- `store/repos.py`'s `create_repo` didn't roll back on failure the way
  `store/chunks.py`'s `insert_chunks` already did (both share the
  "only manage the transaction if I started it" pattern) — made symmetric.
- `store/db.py`'s `_CursorWrapper.lastrowid` re-queried
  `last_insert_rowid()` wrapped in a bare `except Exception: return None`,
  which could silently turn a real DB error into a wrong/`None` `chunk_id`
  — replaced with `apsw.Connection.last_insert_rowid()` directly.

What exists right now:
- `coderag_mcp/api/main.py` — FastAPI app, `/health` endpoint, MCP server
  mounted at `/mcp`. Has a docstring explaining the SDK-version adaptation
  (see below) — read it before touching this file.
- `coderag_mcp/mcp_server/server.py` — the MCP server object (`mcp`), still
  only the dummy `ping` tool. The real search/ask functionality is live,
  but as `POST /ask` (REST), not as MCP tools yet — wiring `index_repo`/
  `search_code`/`ask_repo` onto this `mcp` object (item 1 in "What comes
  next" below) is still pending; the mounting/lifespan wiring in
  `api/main.py` should not need to change when that happens.
- `coderag_mcp/config.py` — typed settings (`pydantic-settings`):
  `public_host`, `voyage_api_key`, `sqlite_db_path`.
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
    `clone.cleanup_clone`. `orchestrator.indexing_service.index_and_store_repo`
    calls this function directly.
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

- `coderag_mcp/store/` (SQLite + `sqlite-vec`, replaces the design doc's
  Postgres/pgvector plan):
  - `db.py` — `get_connection(db_path) -> _APSWWrapper` (type-hinted
    `sqlite3.Connection` for interface familiarity, but the real contract
    is the `apsw`-backed wrapper — don't swap in a real `sqlite3.Connection`,
    it lacks `.begin()`), `init_schema(conn, dim=1024)`. Loads the
    `sqlite-vec` extension; the `.dylib` existence-check fallback in
    `get_connection` is macOS-specific and unverified on the Render/Linux
    deploy target ("What comes next" item 5 below) — SQLite's own `load_extension` has a
    built-in platform-suffix fallback, so this is unconfirmed-risk, not a
    known break.
  - `repos.py` / `chunks.py` — `create_repo`, `get_repo_id_by_url`,
    `insert_chunks`, `search_chunks` (cosine distance via `sqlite-vec`'s
    `vec0` virtual table). Both `create_repo` and `insert_chunks` reach
    into the wrapper's private `_conn.in_transaction` to detect whether
    they own the current transaction (duplicated logic, known deferred
    cleanup — see below).
- `coderag_mcp/embeddings/voyage.py` — `embed_batch(texts, *,
  input_type="document")`. Pass `input_type="query"` when embedding a
  search query (asymmetric model) — see the input_type bug fixed above.
- `coderag_mcp/orchestrator/` (Claude Agent SDK orchestrator):
  - `indexing_service.py` — `index_and_store_repo(conn, repo_url) -> int`,
    idempotent by URL (checks `repos` before re-cloning/re-embedding).
  - `tools.py` — `build_search_server(conn, repo_id)`, the `search_code`
    custom tool exposed as an in-process MCP server via
    `claude_agent_sdk.create_sdk_mcp_server`.
  - `_mcp_compat.py` — **a second, separate `mcp` SDK gotcha, read this
    before touching anything MCP-related in `orchestrator/`:**
    `claude_agent_sdk.create_sdk_mcp_server` is written against the
    mainstream `mcp` SDK's low-level `Server` (decorator-based
    `list_tools()`/`call_tool()`, backed by a `request_handlers: dict[type,
    ...]`, and a callable `ServerResult` RootModel wrapper). This repo's
    pinned `mcp==2.0.0` fork has neither — its `Server` uses
    `add_request_handler(method: str, ...)`, and `ServerResult` is a plain
    non-callable `X | Y | Z` union alias. `_mcp_compat.py` monkeypatches
    `mcp.server.Server` (module-global, unscoped, never reverted) with a
    minimal shim providing just the two decorators and a `_ServerResult`
    stand-in. Verified safe because nothing else in this project imports
    `mcp.server.Server` (`mcp_server/server.py` uses the unrelated
    `mcp.server.mcpserver.MCPServer`) — but if a future dependency bump or
    new code needs the *real* `mcp.server.Server`, it will silently get
    this stub instead, process-wide, with no diagnostic. Root-caused via
    bytecode/source inspection of both packages, not guessed — see
    the module's docstring for the full trail if this needs revisiting.
  - `agents.py` — `RAG_SEARCH`, `CODE_EXPLORER` (`AgentDefinition`s) and
    `fresh_clone(repo_url)`, a context manager around `clone.clone_repo`/
    `cleanup_clone` (always `allow_local_paths=False`).
  - `ask.py` — `ask(conn, repo_id, repo_url, question) -> str`. Clones the
    repo **on every call**, not just when `code-explorer` is actually
    invoked — `ClaudeAgentOptions.cwd` must be set before the orchestrator
    runs, so there's no way to clone lazily without hooking the SDK's
    internal tool-dispatch (out of scope for v1). This is a deliberate,
    documented latency tradeoff, not a bug.
- `coderag_mcp/api/ask_route.py` — `POST /ask` (`AskRequest{repo_url,
  question}` → `AskResponse{answer}`). Indexes on first request, then
  calls `orchestrator.ask.ask()`. Maps `IndexingError` (from either the
  initial index or `ask()`'s re-clone) to 400, everything else to 502.

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
- `POST /ask` does blocking work (git clone, synchronous Voyage HTTP
  calls, sqlite reads/writes) directly on the event loop inside an `async
  def` endpoint, with no `run_in_executor`/`asyncio.to_thread` offload —
  one slow request stalls every other concurrent request the process is
  serving. No connection pooling either: `get_connection()` +
  `init_schema()` (including reloading the `sqlite-vec` extension) run on
  every `/ask` call.
- `embeddings/voyage.py`'s `embed_batch` constructs a new `voyageai.Client()`
  on every call instead of reusing one.
- The "only manage the transaction if I own it" pattern (`not
  conn._conn.in_transaction`) is hand-duplicated across `store/chunks.py`,
  `store/repos.py`, and `orchestrator/indexing_service.py`, reaching into
  the `_APSWWrapper`'s private `_conn` from two different modules. A
  shared `transaction(conn)` helper (and a public `in_transaction`
  property on `_APSWWrapper`) would collapse all three.
- `_mcp_compat.py`'s monkeypatch (see above) and `get_connection()`'s
  `-> sqlite3.Connection` type hint (the real contract needs
  `_APSWWrapper`'s `.begin()`) are both documented-but-real landmines for
  a future contributor trusting the stated interface.

## What comes next

Superseded from the original design doc's Build Order by the
orchestrator/dual-path work (Plan 1, Plan 2, and the
dual-path-orchestrator plan are all done — see "Current status" above).
Remaining, roughly in priority order:

1. Wire the real MCP tools (`index_repo`, `search_code`, `ask_repo`) onto
   the `mcp` object in `mcp_server/server.py`, reusing
   `orchestrator.indexing_service.index_and_store_repo` and
   `orchestrator.ask.ask` rather than duplicating logic — the
   mounting/lifespan code in `api/main.py` should not need changes for
   this. **Do not pass `allow_local_paths=True`** — that flag exists
   solely for tests against a local fixture repo; a real endpoint must
   only ever accept `github.com`/`gitlab.com` URLs.
2. Address the deferred tech debt from the dual-path-orchestrator review
   (see "Known deferred items" above) — at minimum the blocking-I/O-in-
   async-endpoint issue before this is ever load-tested or deployed.
3. Auth (API key), remaining production-readiness pieces from the spec.
   Natural point to promote the hardcoded indexing constants
   (`ALLOWED_HOSTS`, `MAX_REPO_SIZE_MB`, `CLONE_TIMEOUT_S`,
   `MAX_FILE_COUNT`, `PIPELINE_TIMEOUT_S`) to `pydantic-settings`, and to
   revisit the pre-clone size mitigation (currently a
   `--filter=blob:limit=<n>` partial-clone flag plus a post-clone aggregate
   check — no true streaming/disk-quota enforcement yet).
4. Minimal React+Vite+TypeScript frontend (separate plan, deliberately
   deferred — this repo is backend-first).
5. Deploy (Render + Supabase + Vercel per the spec — note `store/db.py`'s
   sqlite-vec extension loading is unverified on Linux, see above) +
   polish the README (architecture diagram, demo GIF, live URL,
   design-decisions section) + ADRs.

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
