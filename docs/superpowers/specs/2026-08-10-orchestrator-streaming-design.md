# Orchestrator live streaming (SSE) — design

## Context

coderag-mcp's backend is fully built, hardened, and verified live (indexing,
SQLite+sqlite-vec store, Voyage embeddings, single-agent Claude Agent SDK
orchestrator, `POST /ask`, real MCP tools, auth, structured logging,
retry/backoff, a dry-run-verified local quickstart). All of that is done and
merged to `main`.

The next goal is a gitingest.com-style frontend — paste a repo URL, ask a
question, and watch it work — with a real differentiator: a live "x-ray"
into the orchestrator's decision-making as it happens (which tool it picks,
what it searches for, what it finds, the final answer streaming in), not
just a spinner followed by a final answer.

This is the first of three related sub-projects, scoped and sequenced
separately because they're genuinely independent subsystems:
1. **This spec: backend streaming support.** Exposes what the orchestrator
   is doing, live, over HTTP. No frontend, no deploy.
2. **Frontend** (React+Vite+TypeScript, gitingest-inspired) — its own
   brainstorm → spec → plan cycle, after this lands, since it needs a real
   stream to consume.
3. **Deploy** — explicitly out of scope. Decided in conversation: the
   `claude` CLI headless-auth problem (`claude_agent_sdk` shells out to the
   `claude` CLI, needing interactive login or `ANTHROPIC_API_KEY` in a
   server context) is a real, fixed cost with limited payoff for a
   portfolio project that already has a strong local-run + demo-video
   story. Local clone-and-run stays the distribution model.

## What gets streamed

Both phases of a question get streamed, since indexing already takes
visible time today with nothing shown for it:
- **Indexing** (clone → chunk → embed), when the repo hasn't been indexed
  yet (skipped entirely on a cache hit — no misleading "indexing" events for
  an already-indexed repo).
- **Orchestration**: every tool call the agent makes (`search_code`,
  `Read`, `Grep`, `Glob`) with its input, a preview of each tool's result,
  any intermediate reasoning text the model emits between tool calls, and
  the final answer streamed token-by-token (not appearing all at once at
  the end).

## Architecture

- `coderag_mcp/orchestrator/ask.py` gains `ask_stream(conn, repo_id,
  repo_url, question) -> AsyncIterator[dict]`: does the same work `ask()`
  does today (clone, build `ClaudeAgentOptions`, iterate `query()`), but
  yields a structured event per message/block instead of concatenating
  text into a final string.
- `ask()` (consumed today by `/ask` and the MCP `ask_repo` tool) becomes a
  thin wrapper: it iterates `ask_stream()`, keeps only `answer_token`
  events, concatenates them, and returns the final string — identical
  external behavior, zero duplicated SDK-interaction logic. This is a
  refactor of already-shipped code, done carefully so `/ask` and `ask_repo`
  are unaffected (same tests must keep passing unchanged).
- New endpoint `POST /ask/stream` (new file `coderag_mcp/api/ask_stream_route.py`,
  mounted alongside the existing `ask_router`) takes the same request body
  as `/ask` (`repo_url`, `question`), same `Depends(require_api_key)` auth,
  and returns a `StreamingResponse` emitting Server-Sent Events. `POST` (not
  `GET`) because the frontend will consume it via `fetch()` +
  `ReadableStream` (decided in conversation — the browser's native
  `EventSource` API can't send custom headers like `X-API-Key` and is
  GET-only; `fetch()` supports both a POST body and header-based auth, so
  there's no reason to constrain this to GET/EventSource).
- Before entering `ask_stream()`, the endpoint drives indexing itself
  (calling `index_and_store_repo_async`, or a thin wrapper around it) and
  emits `indexing_start`/`indexing_done` around that call — skipping both
  events entirely if the repo's already indexed (no existing-repo lookup
  needs its own "indexing" event, just proceed silently to Phase 2).
  `indexing_start`/`indexing_done` bracket the whole clone+chunk+embed
  step as one unit, not per-substep progress — `_clone_chunk_and_embed`
  (`orchestrator/indexing_service.py`) has no internal progress-callback
  points today, and adding them is out of scope here; a demo-sized repo
  indexes in a few seconds (measured ~1.7s for a small repo earlier this
  session), so a coarse start/done pair is enough signal, not a granular
  progress bar.
- `/ask` (existing) and `POST /mcp`'s `ask_repo` tool are both **unchanged**
  in behavior and contract — this is purely additive.

## Event schema

Each SSE message is `data: <json>\n\n`, one JSON object with a discriminant
`type` field:

```
{"type": "indexing_start", "repo_url": "..."}
{"type": "indexing_done", "chunk_count": 42, "duration_s": 3.2}
{"type": "tool_call", "tool": "search_code" | "Read" | "Grep" | "Glob", "input": {...}}
{"type": "tool_result", "tool": "...", "tool_use_id": "...", "output_preview": "...", "is_error": true | false | null}
{"type": "reasoning", "text": "..."}
{"type": "answer_token", "text": "..."}
{"type": "done"}
{"type": "error", "message": "..."}
```

- `output_preview` is truncated (300-500 chars, with a marker if truncated)
  so a large `search_code`/`Read` result doesn't flood the stream.
- `tool_result`'s `tool` field is the name of the tool that produced this
  result (looked up server-side from the `tool_call` that shares its
  `tool_use_id`), so a consumer can correlate a result back to the tool
  that produced it without having to track `tool_use_id`s itself.
  `tool_use_id` is still included alongside it for a consumer that wants
  exact call/result pairing (e.g. multiple concurrent calls to the same
  tool). `is_error` is `ToolResultBlock.is_error` passed through verbatim
  (`true`, `false`, or `null` if the SDK didn't set it) so a failed tool
  call is distinguishable from a successful one.
- `reasoning` events depend on extended thinking being enabled in
  `ClaudeAgentOptions`, which it currently is not — don't expect to see
  `reasoning` events in practice yet. Enabling extended thinking is a
  follow-up, not part of this feature.
- `answer_token` events may include the model's intermediate commentary
  emitted between tool calls (e.g. "Let me search for the auth
  handler..."), not only the true final answer — the stream has no
  separate event type distinguishing "commentary" from "the final
  answer," so a frontend consuming `answer_token` events should not assume
  every one of them belongs to the final answer in isolation. A clean
  separation (if it turns out to matter for the frontend) is a follow-up,
  not solved here.
- `error`'s `message` follows the exact same safe-message policy `/ask`
  already applies (`IndexingError` → its own message, since those are
  client-safe by design; anything else → a generic safe message, never raw
  internals) — same policy, different transport (an event instead of an
  HTTP status code).
- If `ask_stream()` (or the indexing step before it) raises mid-stream, the
  endpoint emits one `error` event and closes the stream cleanly — it
  cannot fall back to a normal HTTP error status, since SSE's headers are
  already committed once streaming starts. If an `error` event arrives
  without a preceding `done`, any `answer_token`s already received are a
  truncated/incomplete answer, not a complete one — a frontend should
  treat the absence of `done` as "this response did not finish
  successfully," even if some answer text was already streamed.

## Testing

- `ask_stream()`: unit tests with a mocked `query()` emitting a scripted
  sequence of `ToolUseBlock`/`ToolResultBlock`/`TextBlock` messages
  (confirm the exact `claude_agent_sdk` message/block shapes for tool
  calls and results against the installed SDK before writing this test —
  this project's established practice, not assumed from training data),
  asserting each maps to the correct event `type`.
- `ask()`: existing test(s) must keep passing unchanged, now exercising
  `ask()` as a consumer of `ask_stream()` — proves the refactor preserves
  exact external behavior.
- `POST /ask/stream`: a real end-to-end test (real running server, real
  HTTP client reading the SSE response), mocking `index_and_store_repo_async`/
  `query()` the same way this project's other transport tests do (proving
  the wire format and endpoint wiring work, not re-proving the domain
  logic already covered elsewhere) — matches this project's established
  "prove the transport for real, mock the expensive domain calls" pattern
  (`tests/test_mcp_server.py`).
- Mid-stream failure: a test forcing `ask_stream()` to raise partway
  through, asserting the endpoint emits a clean `error` event rather than
  crashing the connection or leaking an unhandled exception.
- Full existing suite (currently 88/88) must stay green throughout.
