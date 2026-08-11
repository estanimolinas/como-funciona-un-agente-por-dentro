# Frontend — design

## Context

coderag-mcp's backend is fully built, hardened, and merged to `main`:
indexing, SQLite+sqlite-vec store, Voyage embeddings, a single-agent Claude
Agent SDK orchestrator, `POST /ask` (buffered) and `POST /ask/stream` (SSE,
just shipped — see
`docs/superpowers/specs/2026-08-10-orchestrator-streaming-design.md` for
its full event schema), real MCP tools, optional API-key auth, structured
logging, retry/backoff, and a dry-run-verified local quickstart.

This is the second of three related sub-projects (backend streaming →
**frontend** → deploy, the last explicitly out of scope — decided earlier:
`claude_agent_sdk` shells out to the `claude` CLI, which needs interactive
auth or `ANTHROPIC_API_KEY` in a headless server context, a real fixed
cost with limited payoff for a portfolio project that already has a strong
local-run + demo-video story).

The goal is a gitingest.com-style frontend — paste a repo URL and a
question, hit go — with a real differentiator over a generic chat UI: a
live "x-ray" into the orchestrator's decision-making as it happens (which
tool it picks, what it searches for, what it finds, the final answer
streaming in), not just a spinner followed by a final answer. Target
audience is ML/AI engineers reviewing a GitHub portfolio, so the frontend
needs to read as a technically compelling demo of what the backend can do.

Local-run only, same clone-and-configure distribution model as the
backend — no deploy story for this sub-project either.

## Stack

React + Vite + TypeScript + Tailwind CSS. Vitest + React Testing Library
for tests (zero extra config on top of Vite). New top-level `frontend/`
directory, sibling to `coderag_mcp/`.

**Why Tailwind:** fast, standard setup for a portfolio piece — utility
classes get a clean, dark-mode-friendly look (gitingest's ethos: one
screen, one big input, minimal chrome) without hand-writing much CSS.
Plain CSS was the alternative; rejected only because it costs more time
for the same visual result here, not because Tailwind is uniquely
necessary.

**Why Vite dev server + proxy, not a production build:** `npm run dev`
serves the app on its own port (e.g. 5173) with a proxy to
`localhost:8000` for `/ask`, `/ask/stream`, etc. — standard Vite dev flow,
hot reload, and enough for a two-command local demo (`uvicorn ...` +
`npm run dev`) including the eventual demo video. Because the browser
requests hit the Vite dev server (same origin as the page), the FastAPI
backend needs **no CORS changes** — the proxy makes cross-origin requests
disappear entirely. A production build (`npm run build` + FastAPI serving
static files) was considered and rejected: it adds a build step and a
`StaticFiles` mount to maintain for zero benefit, since deploy is out of
scope and the dev server already covers the demo-video use case.

## Visual direction

Borrow gitingest.com's *ethos*, not its literal look: one screen, a large
centered input, "paste and go" simplicity, dark mode, minimal chrome. Free
choice of exact palette/typography beyond that (not copying gitingest's
specific orange accent or exact layout pixel-for-pixel).

## Flow

1. **Single form, everything up front:** repo URL, question, an optional
   collapsible API-key field, and 2-3 clickable example buttons (repo +
   question pairs, e.g. `pypa/sampleproject` — "How is the package version
   defined?") that fill the form on click. One submit ("Ask") — no
   separate index-then-ask two-step flow, matching gitingest's paste-and-go
   feel and requiring only one request per question (mirrors the backend:
   `POST /ask/stream` drives indexing itself and skips indexing events
   entirely on a cache hit).
2. Submitting **appends a new run card** to a vertical feed and does not
   clear or replace earlier cards — every question asked in the session
   stays visible, each with its own live/finished event log. This needs no
   backend storage; it's plain React state on the page, lost on refresh
   (acceptable — matches the backend's stateless-per-call design, and no
   persistence was requested).
3. Each run card opens its own `POST /ask/stream` connection and renders
   events as a **chronological console-style log** — one line/block per
   event, in arrival order, growing as the stream progresses. No timeline
   graphic, no icons-on-a-line-visualization — plain, readable, and it
   degrades gracefully regardless of how many events a question produces.

### API key handling

A collapsible "API key" field in the form, optional. If filled, its value
is sent as the `X-API-Key` header on every request and persisted to
`localStorage` so it survives a page reload without re-entering. If empty,
no `X-API-Key` header is sent at all — works unchanged against a backend
with `CODERAG_API_KEY` unset (the default, auth disabled).

## Component architecture

```
frontend/
  src/
    App.tsx                  — page shell: header, RepoForm, feed of RunCards
    hooks/useAskStream.ts    — owns the SSE connection + parsing for one run
    components/
      RepoForm.tsx           — URL + question + API-key + example buttons
      RunCard.tsx            — one card: header (repo/question) + its event log
      EventLogLine.tsx       — renders one StreamEvent by `type`
    types.ts                 — StreamEvent union type (mirrors the backend schema)
  vite.config.ts             — dev server + proxy config
  tailwind.config.js
  package.json
  README.md                  — frontend-specific quickstart
```

**`useAskStream(repoUrl, question, apiKey)`** is the single boundary
between "how we talk to the backend" and "how a run looks on screen". It
opens the `fetch()` request (`POST`, not `EventSource` — `EventSource` is
GET-only and can't set `X-API-Key`), reads the body via
`ReadableStream`/`TextDecoder`, and incrementally parses `data: <json>\n\n`
frames — including frames split across chunk boundaries (a `data: {...}`
frame can arrive split by the network; the parser buffers a partial line
until a full frame is available). It exposes `{ events: StreamEvent[],
status: "connecting" | "streaming" | "done" | "error" }` — nothing about
`fetch`/`ReadableStream` leaks past this hook. `RunCard` and
`EventLogLine` only ever see `StreamEvent[]`, so they're testable and
reason-about-able without any network mocking.

**`EventLogLine`** maps each event `type` to a rendering:
- `indexing_start`/`indexing_done` — one-line status text (skipped
  entirely if never received — no fake "indexing" line is synthesized).
- `tool_call` — `tool` name + a compact rendering of `input`.
- `tool_result` — `tool` name (correlated via the event's own `tool`
  field — no client-side matching needed, the backend already does the
  `tool_use_id → tool` lookup), truncated `output_preview`, an error
  indicator if `is_error` is true.
- `reasoning` — rendered if it ever arrives (documented as rare/absent
  today since extended thinking isn't enabled — the UI doesn't assume it
  will show up, it just handles it if it does).
- `answer_token` — appended to a single growing text bubble at the bottom
  of the card, not one line per token.
- `done` — marks the card finished successfully; no visible line (the
  card's own header/border state communicates this).
- `error` — a red error line with `message`, and the card is marked
  finished-with-error. Per the streaming spec's documented caveat, any
  `answer_token`s already received before an `error` (with no `done`) are
  a truncated, not complete, answer — the UI must not present that partial
  text as if it were the finished answer (e.g. gray/label it as
  incomplete rather than styling it identically to a successful answer).

## Error handling

- **Mid-stream `error` event:** rendered inline in the log (see above),
  card marked finished-with-error. This is the backend's own
  documented error channel — not treated as exceptional.
- **Stream ends with no `done` and no `error`** (dropped connection,
  network failure): a client-side inactivity timeout (no event received
  for N seconds — exact value decided at plan time, informed by this
  project's existing 180s orchestrator timeout) marks the card
  "connection lost", styled the same as an `error` line.
- **`fetch()` throws before any data arrives** (backend not running, DNS
  failure, malformed request): caught and rendered as a single error line
  in the card — the page itself never crashes on a bad request.

## Testing

- `useAskStream`: unit-tested with a hand-built `ReadableStream` mock
  emitting scripted SSE chunks, including at least one case where a
  `data: {...}\n\n` frame is deliberately split across two chunks — proves
  the parser buffers correctly rather than dropping or corrupting a
  frame.
- `EventLogLine`: one rendering test per `StreamEvent` `type`, including
  the `error`-without-preceding-`done` "truncated answer" case.
- `RepoForm`: tests that submitting calls the expected callback with the
  form's current values, and that clicking an example button fills the
  form fields.
- No end-to-end tests against a real running backend — that surface is
  already covered by the backend's own test suite
  (`tests/api/test_ask_stream_route.py`); the frontend is tested with the
  network layer mocked at the `fetch`/`ReadableStream` boundary.

## Documentation

- `frontend/README.md`: frontend-specific quickstart (`npm install`,
  `npm run dev`, expects the backend already running on `localhost:8000`).
- Root `README.md`: new "Frontend (optional)" section pointing to
  `frontend/README.md`, making clear it's an optional local addition, not
  required to use the REST/MCP API directly.
- `CLAUDE.md`: updated with the new `frontend/` directory and its
  relationship to the backend, following this project's established
  practice of keeping that file current for a fresh session.
