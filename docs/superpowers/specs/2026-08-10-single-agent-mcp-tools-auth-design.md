# Single-agent orchestrator, real MCP tools, and auth/hardening — design

## Context

The dual-path-orchestrator plan (`docs/superpowers/specs/2026-08-09-orchestrator-rag-architecture-design.md`)
is merged to `main` and verified working end-to-end against real Voyage and
real Claude Agent SDK calls: indexing a small repo and answering one
question took ~32s total, ~1.7s of which was indexing.

Three things remain from `CLAUDE.md`'s "What comes next": wiring real MCP
tools, addressing the deferred tech debt from that plan's whole-branch
review, and adding API key auth. While scoping the MCP tools work, external
review (a colleague, relayed by the user) raised a substantive architecture
critique of the already-shipped orchestrator:

- Start with a single agent before reaching for a multi-subagent design.
- Subagents are ephemeral and dumb — they only have what's explicitly
  injected into their context, and dispatching to one costs tokens and
  latency on every question.
- A single agent should itself be able to discern whether a question calls
  for semantic search (RAG) or exact document/code reading, given both
  tools directly — not have that decision made *for* it by an orchestrator
  that routes to a separate subagent.

This is accepted as a real simplification, not deferred: it's folded into
this design as a revision to already-shipped code (`orchestrator/ask.py`,
`orchestrator/agents.py`), on the same "improve code you're working in"
basis as the transaction-ownership dedup below.

This spec covers three things, in dependency order (2 depends on the
single-agent revision landing first for `ask_repo` to wrap a settled `ask()`;
1 and 3 are independent of each other and of 2):

1. Auth (API key) for `/ask` and `/mcp`.
2. Single-agent orchestrator + real MCP tools (`index_repo`, `search_code`,
   `ask_repo`) on the `mcp` object.
3. Tech-debt hardening (blocking I/O off the event loop, shared SQLite
   connection, Voyage client reuse, transaction-ownership dedup) + promoting
   Plan 2's hardcoded indexing constants to settings.

## 1. Auth (API key)

**Scheme:** a single static API key (`CODERAG_API_KEY` in `config.py`,
default `""`). Sent by clients via the `X-API-Key` header. Matches the
design doc's original "Auth (API key)" line and fits a single-user/demo
portfolio project — no per-client keys, no JWT/OAuth.

**Dev mode:** if `CODERAG_API_KEY` is unset/empty, auth is not enforced.
This is intentional (documented in `CLAUDE.md`, not a bug) — it keeps local
dev and the existing test suite working without every test needing to set
a key.

**Orthogonality:** `/ask` is a normal FastAPI route (`Depends()` works);
`/mcp` is a mounted Starlette sub-app (`Depends()` does not run for routes
inside a mount). Rather than two independent auth implementations, both
adapters delegate to one pure function:

- `coderag_mcp/api/auth.py`:
  - `validate_api_key(provided: str | None) -> bool` — the single source of
    truth: `True` if `settings.coderag_api_key` is empty (dev mode) or
    `provided == settings.coderag_api_key`.
  - `require_api_key(x_api_key: str | None = Header(None))` — a FastAPI
    dependency wrapping `validate_api_key`, raises `HTTPException(401)` on
    failure. Applied to `ask_route.router`'s `/ask` route.
  - `ApiKeyMiddleware` — a small ASGI middleware wrapping `validate_api_key`
    against the `X-API-Key` header, returning a raw 401 response on
    failure. Applied to the `mcp_app` Starlette app before it's mounted at
    `/mcp` in `api/main.py`.
- `/health` stays unauthenticated (standard for infra health checks).

## 2. Single-agent orchestrator + real MCP tools

### Orchestrator revision (`orchestrator/`)

`agents.py`:
- Removes `RAG_SEARCH` and `CODE_EXPLORER` (`AgentDefinition`s no longer
  needed — no subagent dispatch).
- Keeps `fresh_clone(repo_url)` — `Read`/`Grep`/`Glob` still need a real
  `cwd`, so the eager-clone-per-`ask()`-call tradeoff from the original
  plan is unchanged (still no way to clone lazily without hooking the
  SDK's internal tool-dispatch — still out of scope).
- Adds `ORCHESTRATOR_SYSTEM_PROMPT: str` — instructs the model: use
  `search_code` for conceptual/"how does X work" questions where semantic
  similarity matters; use `Read`/`Grep`/`Glob` for exact/structural
  questions where current file:line accuracy matters; choose per-question,
  don't default to one.

`ask.py`:
- `ask(conn, repo_id, repo_url, question)` unchanged in signature. Internals
  simplify: `ClaudeAgentOptions(cwd=str(repo_dir), system_prompt=
  ORCHESTRATOR_SYSTEM_PROMPT, allowed_tools=["mcp__search__search_code",
  "Read", "Grep", "Glob"], mcp_servers={"search": search_server})` — no
  `agents=`, no `"Agent"` in `allowed_tools`. One `query()` call, no
  subagent dispatch round-trip.
- Answer extraction (already fixed to filter `AssistantMessage`/`TextBlock`
  via `isinstance`) is unaffected by this change.

**Test impact:** `tests/orchestrator/test_ask.py` loses its
`options.agents.keys() == {...}` assertion, gains one asserting
`allowed_tools` contains the four direct tools and no `"Agent"`.
`tests/orchestrator/test_agents.py` loses the `CODE_EXPLORER`/`RAG_SEARCH`
tests, gains one for `ORCHESTRATOR_SYSTEM_PROMPT` existing and mentioning
both tool families (a light content check, not a behavior test — the real
behavior check is the live end-to-end test, not a unit test hunting for
keywords in a prompt string).

### Real MCP tools (`mcp_server/server.py`)

Three tools, each a thin wrapper reusing `orchestrator/` — no logic
duplicated between the REST (`/ask`) and MCP transports:

- `index_repo(repo_url: str) -> str` → calls the shared index-on-first-use
  helper (see below), returns a confirmation string with the `repo_id`.
- `search_code(repo_url: str, query: str, top_k: int = 5) -> str` →
  index-on-first-use, then `store.chunks.search_chunks` directly (pure
  retrieval — this tool never touches the orchestrator or the Agent SDK,
  same as the in-process `search_code` tool the orchestrator itself uses).
- `ask_repo(repo_url: str, question: str) -> str` → index-on-first-use,
  then `orchestrator.ask.ask(...)`.

**Shared index-on-first-use logic:** currently lives inline in
`api/ask_route.py` (`index_and_store_repo` call + error mapping). Both
`api/ask_route.py` and `mcp_server/server.py` need it, so it's extracted
to a single call site — `orchestrator.indexing_service.index_and_store_repo`
already *is* that shared core (it's already domain logic, not API-layer
logic); no new module needed, `mcp_server/server.py`'s tools just import
and call it directly, same as `ask_route.py` does today. This keeps `api/`
and `mcp_server/` as two thin, independent adapters over one domain core
(`orchestrator/`), matching auth's core-plus-adapters shape.

**Auth:** the `ApiKeyMiddleware` from part 1 covers the whole `/mcp` mount,
so these tools don't handle auth themselves.

**Connection:** these tools use the shared global SQLite connection from
part 3, not their own `get_connection()` call.

## 3. Tech-debt hardening + settings

### Blocking I/O off the event loop

- `api/ask_route.py`: the calls to `index_and_store_repo(...)` and
  `run_ask(...)` (renamed import for `orchestrator.ask.ask`) are wrapped in
  `asyncio.to_thread(...)` at the `async def ask_endpoint` call site.
- `orchestrator/ask.py`: `ask()` already `await`s the SDK's `query()`
  (naturally async); the synchronous `with fresh_clone(repo_url)` block
  around it is offloaded via `asyncio.to_thread` internally so the clone
  itself doesn't block the loop either.
- `mcp_server/server.py`'s new tools get the same treatment — MCP tool
  handlers are already `async def`, so they wrap their sync calls the same
  way.

### Shared SQLite connection

- `store/db.py`: `get_connection(db_path)` stays as the low-level factory
  (used by tests, which want isolated per-test databases), but
  `api/main.py`'s lifespan opens **one** connection at startup (same
  lifespan pattern already used for `mcp_app`'s session manager) and stores
  it on `app.state.db_conn`. `init_schema` runs once at startup, not per
  request.
- A module-level `asyncio.Lock` (in a small shared location, e.g.
  `coderag_mcp/store/db.py` or `api/main.py`) is acquired around each
  `asyncio.to_thread`-offloaded DB operation, since SQLite doesn't tolerate
  real concurrent writes and multiple executor threads could otherwise hit
  the same connection at once.
- `ask_route.py` and `mcp_server/server.py`'s tools both read this shared
  connection (via `app.state` for the REST route; the MCP server object
  needs an equivalent handle — likely set once when `mcp_server/server.py`
  is wired up, exact mechanism to confirm during implementation against
  the installed MCP SDK's lifespan hooks, same category of "verify against
  the installed version" already established for this codebase).

### Voyage client reuse

- `embeddings/voyage.py`: `voyageai.Client(...)` moves from inside
  `embed_batch` to a module-level lazily-initialized singleton (created on
  first use, reused after), so repeated `embed_batch` calls don't pay
  client/session setup cost each time.

### Transaction-ownership dedup

- `store/db.py`'s `_APSWWrapper` gains a public `in_transaction` property
  (thin wrapper over the existing private `_conn.in_transaction`) and a
  `transaction(conn)` context manager: begins a transaction if one isn't
  already active, commits on clean exit, rolls back on exception — mirrors
  the try/except/rollback-if-owner shape already in `insert_chunks` and
  (after the whole-branch-review fix) `create_repo`.
- `store/chunks.py`'s `insert_chunks`, `store/repos.py`'s `create_repo`,
  and `orchestrator/indexing_service.py`'s `index_and_store_repo` switch to
  `with transaction(conn):` instead of each hand-rolling
  `not conn._conn.in_transaction` / try/except/rollback. Removes the
  private-attribute reach-through from three separate modules.

### Settings promotion

- `config.py`'s `Settings` gains: `allowed_hosts: list[str] =
  ["github.com", "gitlab.com"]`, `max_repo_size_mb: int`, `clone_timeout_s:
  int`, `max_file_count: int`, `pipeline_timeout_s: int` — same default
  values as the current hardcoded constants in `indexing/clone.py` and
  `indexing/pipeline.py`.
- Those modules read from `get_settings()` instead of module-level
  constants. No behavior change at default settings; existing tests that
  currently monkeypatch the module constants directly will need to
  monkeypatch settings instead (confirm exact mechanism per test during
  implementation — `get_settings()` has no `@lru_cache`, so this should be
  a drop-in swap without needing a fixture to reset a cache).

### Explicitly out of scope (stays deferred)

- `_mcp_compat.py`'s monkeypatch — inherent to the `mcp==2.0.0` version
  gap; not resolved without a dependency upgrade, which is its own
  separate risk to take on deliberately, not as a side effect of this work.
- `sqlite-vec`'s `.dylib`-only fallback — verified only when this is
  actually deployed to Linux (Render), tracked as a deploy-time check, not
  fixed speculatively now.

## Testing

- New: `tests/api/test_auth.py` (or extend `test_ask_route.py`) — 401
  without/with-wrong `X-API-Key` when `CODERAG_API_KEY` is set, 200 when
  correct, unauthenticated passthrough when unset. A real end-to-end check
  that the `/mcp` mount's `ApiKeyMiddleware` actually rejects, not just a
  unit test of `validate_api_key` in isolation — matches this project's
  established "no shortcuts, test the real transport" standard
  (`tests/test_mcp_server.py`'s existing pattern).
- Revised: `tests/orchestrator/test_ask.py`, `tests/orchestrator/test_agents.py`
  per the single-agent changes above.
- New: `tests/mcp_server/test_tools.py` (or wherever `mcp_server/` tests
  live) — real end-to-end test per tool (`index_repo`, `search_code`,
  `ask_repo`) over a real MCP client connection, same pattern as the
  existing `test_ping_tool_over_streamable_http`, not mocked.
- New/revised: tests covering the shared-connection + lock behavior under
  concurrent `asyncio.to_thread` calls (at least two calls that would
  interleave without the lock), and the `transaction(conn)` helper
  (nested-transaction and rollback-on-exception cases) replacing what
  `test_indexing_service.py`/`test_chunks.py`/`test_repos.py` currently
  test against the duplicated logic.
- Full suite must stay green throughout — this project's standing rule.

## Open questions to resolve during implementation (not blocking this spec)

- Exact mechanism for the MCP server object to reach the shared DB
  connection (`app.state` equivalent for the standalone `mcp` object,
  which isn't itself a FastAPI app) — confirm against the installed
  `mcp==2.0.0` SDK's actual API before writing code, per this project's
  established practice of never trusting training-data assumptions about
  this SDK.
- Where exactly `ApiKeyMiddleware` should assemble into the ASGI stack
  relative to `mcp_app.router.lifespan_context` — confirm ordering doesn't
  break the existing lifespan wiring documented in `api/main.py`'s
  docstring.
