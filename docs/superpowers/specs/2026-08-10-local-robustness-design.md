# Local robustness + nanoLoop-style onboarding — design

## Context

The backend is fully built and verified end-to-end (real Voyage, real Claude
Agent SDK) as of the single-agent/MCP-tools/auth plan
(`docs/superpowers/specs/2026-08-10-single-agent-mcp-tools-auth-design.md`).

The original next step under discussion was a publicly hosted demo, but that
surfaced a real, unsolved blocker: `claude_agent_sdk` shells out to the
`claude` CLI as a subprocess, which needs either interactive login or
`ANTHROPIC_API_KEY`-based auth inside a headless server image — not solved,
and deliberately deferred, not in scope here.

Reframed goal (this spec): make the repo genuinely **clone-and-run-locally**
friendly, nanoLoop-style — a developer clones it, sets their own API keys,
and runs it either as the REST API or as an MCP server added to their own
Claude Code config — and hold the backend + AI-orchestrator layer to a
higher robustness bar while doing it. A portfolio demo video is the eventual
payoff, explicitly deferred to *after* this lands (recording against
not-yet-final behavior would mean re-recording).

**Explicitly out of scope:** the React+Vite frontend, public hosted deploy
(Render/Docker/headless-CLI-auth), rate limiting/cost-control for public
traffic, CORS. All already discussed and deferred.

## 1. Startup config validation

- `coderag_mcp/config.py` gains `validate_settings(settings: Settings) ->
  None`: raises `RuntimeError` with a clear, actionable message if
  `settings.voyage_api_key` is empty — e.g. `"VOYAGE_API_KEY is required —
  set it in .env or the environment. See README.md's Quickstart."`.
  `CODERAG_API_KEY` is NOT validated here — empty is a supported dev-mode
  value (already documented behavior), not a misconfiguration.
- Called once, at startup, from both `api/main.py`'s `create_app()` and
  `mcp_server/server.py`'s `_lifespan` — one function, two call sites, no
  duplicated validation logic between the two transports (same
  core-plus-adapters shape the auth work already established).
- Fails fast: the server refuses to start rather than accepting requests and
  failing confusingly on the first real Voyage call.

## 2. Voyage retry/backoff

- `coderag_mcp/embeddings/voyage.py`'s `embed_batch` wraps the
  `client.embed(...)` call with up to 3 total attempts, exponential backoff
  (1s, 2s between attempts — i.e. sleep before attempt 2 and attempt 3, not
  after the last failure).
- Retries only on transient `voyageai.error` types, confirmed against the
  installed SDK: `APIConnectionError`, `RateLimitError`, `ServerError`,
  `ServiceUnavailableError`, `Timeout`, `TryAgain`. Everything else
  (`AuthenticationError`, `InvalidRequestError`, `MalformedRequestError`,
  the generic `APIError`, and any non-`voyageai.error` exception) fails
  immediately, no retry — retrying an auth failure or a malformed request
  wastes time and produces a worse error message, not a better one.
- Uses `time.sleep` (not `asyncio.sleep`) — `embed_batch` is a synchronous
  function that already runs inside `asyncio.to_thread` (via
  `run_db_sync`/direct `asyncio.to_thread` calls at its call sites); sleeping
  synchronously there blocks only that worker thread, not the event loop.
- Each retry attempt is logged (see Logging below) with the attempt number
  and the exception that triggered it.

## 3. Orchestrator timeout

- `coderag_mcp/orchestrator/ask.py`'s `ask()` gains a keyword-only parameter
  `timeout_s: float = 180.0` and wraps the `async for message in query(...)`
  loop in `async with asyncio.timeout(timeout_s):` (Python 3.11+ stdlib,
  matches this project's `requires-python` floor). 180s gives wide margin
  over the ~32s measured in this session's live end-to-end test. The
  parameter (not a hardcoded constant) is what lets the test below use a
  short override instead of actually waiting 180s.
- On timeout, `TimeoutError` propagates naturally. No new exception-mapping
  code needed: `api/ask_route.py`'s existing `except Exception` → generic
  502 and `mcp_server/server.py`'s three tools' existing `except Exception`
  → generic safe-message mapping (both already built in the prior plan)
  already cover it correctly — a timeout is exactly the kind of internal
  failure that mapping exists to hide from the client.
- The real gap this closes is diagnostic, not behavioral: today a stuck
  `claude` CLI subprocess would hang the request indefinitely with no signal
  to a local developer about why. The timeout plus the logging below turns
  that into a bounded wait and a clear log line ("orchestrator query timed
  out after 180s").

## 4. Structured JSON logging

- New `coderag_mcp/logging_config.py`: `configure_logging() -> None` installs
  a custom `logging.Formatter` subclass that emits one JSON object per line
  (`timestamp`, `level`, `logger`, `message`, plus any `extra=` fields passed
  to the log call). No new dependency — a JSON formatter is ~20 lines against
  stdlib `logging`.
- Called once, at startup, from the same two places as config validation
  (`create_app()`, `mcp_server/server.py`'s `_lifespan`) — before
  `validate_settings` runs, so even the startup failure path logs cleanly.
- `coderag_mcp/indexing/chunker.py` and `pipeline.py` already use
  `logging.getLogger(__name__)` — unaffected in code, their output just
  becomes JSON-formatted once this is wired in.
- New logging added at points that are silent today:
  - `embeddings/voyage.py`: each attempt/retry/final failure of `embed_batch`.
  - `orchestrator/ask.py`: question start (repo_url, question length — not
    full question text, to avoid logging potentially sensitive query
    content by default), completion (duration), and timeout.
  - `orchestrator/indexing_service.py`: index start/end per repo_url,
    duration, chunk count.
  - Any `except Exception` block that currently only re-raises or returns a
    generic message without logging the real exception first.

## 5. README quickstart + `.env.example`

- New `.env.example` at repo root: `VOYAGE_API_KEY=` and `CODERAG_API_KEY=`
  (commented as optional/dev-mode), each with a one-line comment on where to
  get/what it does.
- `README.md` gains a "Quickstart" section with concrete, verified steps:
  1. `git clone` + `cd`
  2. `cp .env.example .env` + fill in `VOYAGE_API_KEY`
  3. `pip install -e .`
  4. `uvicorn coderag_mcp.api.main:app --reload`
  5. A `curl -X POST localhost:8000/ask -d '{"repo_url": "...", "question":
     "..."}'` example
  6. Adding coderag-mcp as an MCP server in Claude Code — exact syntax
     (`claude mcp add` or config file) confirmed against the installed CLI
     before being written into the README, not assumed from memory (same
     verify-before-writing discipline already established in this project
     for the `mcp`/`claude-agent-sdk` SDKs).
- **The whole quickstart is dry-run tested for real** before being
  considered done: clone into a fresh temp directory, follow the written
  steps exactly, confirm each one works as written. Steps are not documented
  without having been run.

## Testing

- `validate_settings`: unit tests for empty/non-empty `voyage_api_key`.
- `embed_batch` retry: tests mocking `voyageai.Client.embed` to raise each
  retryable error type (succeeds after N retries) and each non-retryable
  type (fails immediately, no retry) — using real `voyageai.error` exception
  classes, not generic `Exception`/`RuntimeError` stand-ins, so the
  retryable/non-retryable classification is actually exercised.
- Orchestrator timeout: a test with a `query()` mock that never yields,
  wrapped with a short timeout override (not the real 180s) to keep the test
  fast, asserting `TimeoutError` propagates.
- Logging: a smoke test asserting `configure_logging()` produces
  valid-JSON-per-line output (parse each line as JSON, don't just check it
  doesn't crash).
- Quickstart: verified manually (dry-run in a fresh clone), not via
  automated test — this is a documentation/DX deliverable, not code.
- Full suite must stay green throughout (currently 71/71).
