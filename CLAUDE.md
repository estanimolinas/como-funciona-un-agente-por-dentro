# CodeRAG-MCP — context for a fresh Claude session

Read this before doing anything else in this repo.

## What this is

A portfolio backend project: code-aware RAG over public git repositories,
served both as a REST API and as an MCP server (Streamable HTTP transport).
Indexes a repo with AST-aware chunking (tree-sitter, function/class-level,
not naive line-splitting), embeds chunks with Voyage AI's `voyage-code-3`,
stores vectors in SQLite/`sqlite-vec`, and answers questions with file:line
citations via a Claude Agent SDK **single-agent** orchestrator (`POST /ask`,
and the MCP `ask_repo` tool) that has both semantic search
(`mcp__search__search_code`) and exact file tools (`Read`/`Grep`/`Glob`)
available directly, and chooses between them per question.

**Architecture note:** the original design doc (linked below) specified
Postgres/pgvector and a single retrieval-then-generate RAG endpoint. That was
superseded before implementation by
`docs/superpowers/specs/2026-08-09-orchestrator-rag-architecture-design.md`
(SQLite+`sqlite-vec` instead of Postgres) and then again by
`docs/superpowers/specs/2026-08-10-single-agent-mcp-tools-auth-design.md`,
which collapsed that spec's dual-path orchestrator (a top-level agent
dispatching to separate `rag-search`/`code-explorer` subagents via the Agent
tool) into a single top-level agent given both tool families up front —
dispatching added a token/latency round-trip for a decision the model can
make directly. **If you see references to `RAG_SEARCH`, `CODE_EXPLORER`, or
`fresh_clone` anywhere (old docs, old memory), they describe the superseded
dual-path design — the current orchestrator is single-agent, see
`coderag_mcp/orchestrator/agents.py`'s docstring for the full rationale.**
The original design doc is still correct for architecture/security-
constraints background; treat its store/RAG-endpoint specifics as
superseded by the two specs above.

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

**Plans 1, 2, the dual-path-orchestrator plan (later collapsed to
single-agent), and the single-agent/MCP-tools/auth plan — all done, 71/71
tests passing.** See `docs/superpowers/plans/2026-08-08-coderag-mcp-scaffold-and-spike.md`,
`docs/superpowers/plans/2026-08-08-indexing-pipeline.md`, and
`docs/superpowers/plans/2026-08-09-dual-path-orchestrator.md` for the
earlier plans' history. This branch (`worktree-single-agent-mcp-tools-auth`)
did the single-agent collapse, wired the real MCP tools (`index_repo`,
`search_code`, `ask_repo`) onto the `mcp` object, added API-key auth to both
transports, and then went through a final whole-branch review that found
and fixed 14 more issues — worth knowing about since they're the kind of
thing a fresh session might reintroduce:

- `config.py`'s `allowed_hosts` env var required JSON-array syntax and
  several fields were unprefixed, so a generic env var like `ALLOWED_HOSTS`
  could unintentionally override this app's setting. Fixed with
  `env_prefix="CODERAG_"` on `Settings` (every field is now
  `CODERAG_<FIELD>`, e.g. `CODERAG_API_KEY`, except `voyage_api_key`, which
  opts out via an explicit `validation_alias="VOYAGE_API_KEY"` to match
  Voyage's own convention), plus a `field_validator` so `allowed_hosts`
  accepts either a comma-separated string or a JSON array.
- `get_settings()` did blocking file I/O (`Settings()` re-reads `.env`) on
  every call, including from `ApiKeyMiddleware.dispatch` on every `/mcp`
  request. Fixed with `@lru_cache` on `get_settings()`.
- API key comparison used `==` (a timing side-channel). Fixed with
  `secrets.compare_digest` in `api/auth.py`'s `validate_api_key`.
- `search_code`'s embed→search→format logic was duplicated between
  `orchestrator/tools.py` (the SDK in-process tool) and `mcp_server/server.py`
  (the real MCP tool) — evidence it was a real problem: the same db_lock-scope
  bug got found and fixed independently in each copy earlier in this branch's
  history. Extracted into `orchestrator/search_service.py`'s
  `search_and_format(conn, repo_id, query, top_k=5)`, used by both; `top_k`
  is clamped there (`MAX_TOP_K = 50`) so one call can't pull the whole corpus
  into a single response.
- `db_lock` (in `store/db.py`) was held across the *entire* first-time-index
  pipeline (git clone up to 60s, embedding up to 120s, not just the final DB
  write), blocking every other concurrent DB-touching call on **both**
  transports for up to ~3 minutes. Fixed by splitting
  `orchestrator/indexing_service.py`'s indexing into non-DB work
  (`_clone_chunk_and_embed`, run via plain `asyncio.to_thread`, unlocked) and
  DB work (`_store_repo_and_chunks`, run via `run_db_sync`, locked); real
  callers (`api/ask_route.py`, `mcp_server/server.py`'s three tools) now call
  the new `index_and_store_repo_async`, which only holds the lock around the
  existing-repo check and the final store. The original synchronous
  `index_and_store_repo` (all-in-one) is kept for direct/test use where
  there's no concurrent access to `conn` to worry about.
- `db_lock` was an `asyncio.Lock`, which can raise `RuntimeError` under
  contention across two different event loops. Fixed by switching to a plain
  `threading.Lock`, acquired/released *inside* the `to_thread`-spawned worker
  (not on the event-loop side) — see `run_db_sync`'s updated docstring.
- The three MCP tools let any exception propagate raw to the client, unlike
  `/ask` (which maps `IndexingError` to a client-safe message and everything
  else to a generic one). Fixed with the same two-tier mapping in
  `mcp_server/server.py`'s `index_repo`/`search_code`/`ask_repo` (MCP tools
  can't raise `HTTPException`, so they catch and return the safe text
  instead).
- Several smaller fixes: `index_repo`'s docstring claimed a `repo_id`
  handshake `search_code`/`ask_repo` don't actually support; `create_app()`
  closed over a module-level `settings` snapshot instead of reading fresh
  (now reads `get_settings()` inside the function body, consistent with
  `mcp_server/server.py`'s `_lifespan`, safe post-`@lru_cache`); a comment
  documenting why `mcp.streamable_http_app()`'s shared-state mutation is
  harmless; `coderag.db` added to `.gitignore`; a missing docstring on
  `embeddings/voyage.py`'s `_get_client`.

**In addition, the dual-path-orchestrator plan's whole-branch review (before
its later collapse to single-agent) found and fixed 5 correctness/robustness
bugs** — still relevant since the underlying code they touched is still
here:
- `embeddings/voyage.py`'s `embed_batch` was embedding search queries with
  `input_type="document"` (the corpus-side setting) instead of `"query"` —
  `voyage-code-3` is asymmetric, so this silently degraded retrieval
  quality with no error. Fixed with an `input_type` parameter, defaulting
  to `"document"`; query-embedding call sites pass `"query"`.
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
  mounted at `/mcp` (behind `ApiKeyMiddleware`, see `api/auth.py` below).
  Has a docstring explaining the SDK-version adaptation (see below) — read
  it before touching this file.
- `coderag_mcp/api/auth.py` — API key auth, one validation core
  (`validate_api_key`, constant-time compare via `secrets.compare_digest`)
  with two adapters: `require_api_key` (FastAPI `Depends`, for `/ask`) and
  `ApiKeyMiddleware` (ASGI middleware, for the mounted `/mcp` sub-app, where
  `Depends()` never runs). Auth is disabled entirely when `CODERAG_API_KEY`
  is unset/empty (the default).
- `coderag_mcp/mcp_server/server.py` — the MCP server object (`mcp`), with
  four tools: `ping` (health check), `index_repo`, `search_code`, `ask_repo`.
  All three real tools map `IndexingError` to a client-safe message and
  everything else to a generic one, matching `/ask`'s posture — never let a
  raw exception (which could leak clone stderr/server paths) reach the
  client.
- `coderag_mcp/config.py` — typed settings (`pydantic-settings`),
  `env_prefix="CODERAG_"`: `app_name`, `public_host`, `voyage_api_key`
  (opts out of the prefix, reads `VOYAGE_API_KEY`), `sqlite_db_path`,
  `api_key` (reads `CODERAG_API_KEY`), `allowed_hosts`, `max_repo_size_mb`,
  `clone_timeout_s`, `max_file_count`, `pipeline_timeout_s`. `get_settings()`
  is `@lru_cache`d.
- `tests/test_mcp_server.py` — real end-to-end test: spins up a real
  `uvicorn` server on a real socket, connects with a real MCP client, calls
  the real tools (`ping`, `index_repo`, `search_code`, `ask_repo`), and
  verifies `/mcp` auth and that `IndexingError`/generic-exception mapping
  doesn't leak internals. Not mocked. This is the pattern to follow for
  testing MCP tools going forward.
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
    it is never passed as `True` from any real HTTP/MCP call site.
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
    `clone.cleanup_clone`. `orchestrator.indexing_service` calls this
    function directly.
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
    it lacks `.begin()`), `init_schema(conn, dim=1024)`. `db_lock` is a
    `threading.Lock` (not `asyncio.Lock` — see "Current status" above);
    `run_db_sync(fn, *args, **kwargs)` acquires it inside the
    `asyncio.to_thread`-spawned worker, not on the event loop. Loads the
    `sqlite-vec` extension; the `.dylib` existence-check fallback in
    `get_connection` is macOS-specific and unverified on the Render/Linux
    deploy target ("What comes next" item below) — SQLite's own
    `load_extension` has a built-in platform-suffix fallback, so this is
    unconfirmed-risk, not a known break.
  - `repos.py` / `chunks.py` — `create_repo`, `get_repo_id_by_url`,
    `insert_chunks`, `search_chunks` (cosine distance via `sqlite-vec`'s
    `vec0` virtual table). Both `create_repo` and `insert_chunks` reach
    into the wrapper's private `_conn.in_transaction` to detect whether
    they own the current transaction (duplicated logic, known deferred
    cleanup — see below).
- `coderag_mcp/embeddings/voyage.py` — `embed_batch(texts, *,
  input_type="document")`. Pass `input_type="query"` when embedding a
  search query (asymmetric model). `_get_client()` lazily builds and caches
  the shared `voyageai.Client`.
- `coderag_mcp/orchestrator/` (Claude Agent SDK single-agent orchestrator):
  - `indexing_service.py` — idempotent-by-URL indexing. `index_and_store_repo
    (conn, repo_url) -> int` is the plain synchronous, all-in-one version
    (clone+chunk+embed+store), used directly by tests and any caller with
    exclusive, non-concurrent access to `conn`.
    `index_and_store_repo_async(conn, repo_url) -> int` is what real
    callers (`api/ask_route.py`, `mcp_server/server.py`) use: it splits the
    work so `db_lock` (via `run_db_sync`) is only held for the existing-repo
    check and the final store, not for cloning/embedding.
  - `search_service.py` — `search_and_format(conn, repo_id, query, top_k=5)
    -> str`, the single shared implementation of embed-query → search →
    format-as-text, used by both `tools.py`'s SDK tool and
    `mcp_server/server.py`'s real MCP tool. Clamps `top_k` to `MAX_TOP_K=50`.
  - `tools.py` — `build_search_server(conn, repo_id)`, the `search_code`
    custom tool exposed to the single-agent orchestrator as an in-process
    MCP server via `claude_agent_sdk.create_sdk_mcp_server`. Thin adapter
    over `search_service.search_and_format` — see its module docstring.
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
  - `agents.py` — `ORCHESTRATOR_SYSTEM_PROMPT`, the single-agent's system
    prompt (see its docstring for why the earlier two-`AgentDefinition`
    dispatch design was collapsed into this one agent).
  - `ask.py` — `ask(conn, repo_id, repo_url, question) -> str`. Clones the
    repo **on every call**, not just when file-reading tools are actually
    used — `ClaudeAgentOptions.cwd` must be set before the orchestrator
    runs, so there's no way to clone lazily without hooking the SDK's
    internal tool-dispatch (out of scope for v1). This is a deliberate,
    documented latency tradeoff, not a bug.
- `coderag_mcp/api/ask_route.py` — `POST /ask` (`AskRequest{repo_url,
  question}` → `AskResponse{answer}`), behind `require_api_key`. Indexes on
  first request via `index_and_store_repo_async`, then calls
  `orchestrator.ask.ask()`. Maps `IndexingError` (from either the initial
  index or `ask()`'s re-clone) to 400, everything else to 502.

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
- `embeddings/voyage.py`'s `embed_batch` constructs the client lazily but
  still round-trips to Voyage synchronously inside whatever thread called
  it — fine given the current `asyncio.to_thread` offload pattern, just
  noting there's no batching/retry/backoff logic yet.
- `_mcp_compat.py`'s monkeypatch (see above) and `get_connection()`'s
  `-> sqlite3.Connection` type hint (the real contract needs
  `_APSWWrapper`'s `.begin()`) are both documented-but-real landmines for
  a future contributor trusting the stated interface.
- The pre-clone repo-size mitigation is a `--filter=blob:limit=<n>`
  partial-clone flag plus a post-clone aggregate check — no true
  streaming/disk-quota enforcement yet.

## What comes next

Superseded from the original design doc's Build Order by the
orchestrator/single-agent/auth work (all done — see "Current status"
above). Remaining, roughly in priority order:

1. Minimal React+Vite+TypeScript frontend (separate plan, deliberately
   deferred — this repo is backend-first).
2. Deploy (Render + Supabase + Vercel per the spec — note `store/db.py`'s
   sqlite-vec extension loading is unverified on Linux, see above) +
   polish the README (architecture diagram, demo GIF, live URL,
   design-decisions section) + ADRs.
3. Any of the "Known deferred items" above worth addressing before a
   public demo — none are blocking, but the repo-size streaming enforcement
   is the most likely to matter under real load.

## How to work in this repo

- Python 3.11+, venv at `.venv/` (`./.venv/bin/pytest`, `./.venv/bin/pip`).
- `./.venv/bin/pytest -v` — run the test suite before and after any change.
- Follow the same workflow used to build this: brainstorm/clarify scope
  changes with the human partner first (the design doc is the source of
  truth — don't silently deviate from it), then `writing-plans` to produce
  a task-by-task plan, then `subagent-driven-development` to execute it
  with per-task review and a final whole-branch review. Don't skip the
  review loop — it's what caught real bugs in every plan so far (see
  "Current status" above for the fullest list).
- No LangChain, no DeepAgents, no OpenShell — those belong to nanoLoop, not
  here.
