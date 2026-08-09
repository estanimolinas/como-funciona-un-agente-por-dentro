---
title: CodeRAG-MCP — Dual-path orchestrator (RAG + agentic exploration)
status: approved
date: 2026-08-09
---

# Dual-path orchestrator — Design

## Summary

Reformulates Plans 3+ of the original backend design
(`docs/superpowers/specs/2026-08-08-coderag-mcp-backend-design.md`) around a single
insight from working through the RAG-vs-agent tradeoff conversationally: some questions
about a codebase are answered better by semantic retrieval (RAG), others by exact
structural search (grep/read on the real files). Rather than picking one, the backend
routes each question to whichever fits, via an **orchestrator agent** built on the
**Claude Agent SDK**, with two subagents:

- `rag-search` — semantic search over embedded chunks (SQLite + `sqlite-vec`).
- `code-explorer` — structural search over a fresh clone of the actual repo, using
  built-in Read/Grep/Glob tools.

The UX also changes to match this: a single gitingest.com-style page — paste a repo URL
and a question, get an answer — replacing the original two-step "index, then ask"
REST flow. MCP is deferred to a phase 2 (see Roadmap): the end users of phase 1 are
humans in a browser, not MCP clients, so building the MCP tool surface now would be
speculative scope with no consumer.

**What this supersedes from the original design doc:** the Postgres/pgvector store, the
`POST /repos` + `GET /repos/{id}` + `POST /repos/{id}/ask` REST shape, and the "wire MCP
tools" build-order step (now phase 2). **What still applies unchanged:** the indexing
pipeline built in Plan 2 (`coderag_mcp/indexing/`), the security model (host allowlist,
size/timeout caps), and the general spirit of the project (small, defensible, real
production quality over breadth).

## Scope

In scope:
- SQLite + `sqlite-vec` persistence layer (repos, chunks with embeddings).
- Voyage `voyage-code-3` embedding client.
- Claude Agent SDK orchestrator with two programmatically defined subagents.
- `POST /ask {repo_url, question}` single endpoint: indexes on first request (cached
  after), routes the question, returns an answer with citations.
- Minimal gitingest-style frontend (repo URL + question in, answer out).

Out of scope (deferred — see Roadmap):
- MCP tool wiring (phase 2).
- Force re-index / cache invalidation UX (repo is indexed once, reused after).
- Multi-language support beyond Python (unchanged from original doc).
- Auth, rate limiting, CI polish (unchanged from original doc's later steps).

## Architecture

```
Browser (single page: repo URL + question)
        │  HTTPS
        ▼
FastAPI: POST /ask {repo_url, question}
        │
        ├─ 1. repo already indexed (by URL, in SQLite)?
        │      no  → indexing.pipeline.index_repo() → embed chunks (Voyage) → store
        │      yes → skip straight to 2
        │
        ├─ 2. Orchestrator (Claude Agent SDK, query())
        │      routes the question to one or both subagents based on their
        │      `description` — no hardcoded keyword routing
        │
        │      ┌────────────────────┬─────────────────────────┐
        │      ▼                    ▼
        │  rag-search           code-explorer
        │  tool: search_code    tools: Read, Grep, Glob
        │  (sqlite-vec cosine   scoped to a fresh on-demand
        │   similarity search)  clone of the repo (temp dir,
        │                       deleted after the request)
        │
        └─ 3. Orchestrator synthesizes final answer + file:line citations
```

Local dev and deploy target: unchanged philosophy from the original doc (free-tier
friendly), but SQLite removes the need for a separate Postgres/Supabase instance
entirely — the DB is a file shipped alongside the API process. This is the main reason
for the SQLite choice: fewer moving parts to deploy and demo, not a performance claim.

## Components

- **`indexing/`** — unchanged from Plan 2. `index_repo()` remains the sole entry point
  for clone → chunk.
- **`embeddings/`** — Voyage AI client (`voyage-code-3`), batch-embeds `Chunk.source` for
  each chunk produced by `index_repo()`.
- **`store/`** — SQLite access via the stdlib `sqlite3` driver with the `sqlite-vec`
  extension loaded at connection time (`vec0` virtual table for chunk embeddings, cosine
  distance). No ORM: rejected SQLAlchemy+Alembic for this layer — the schema is small,
  stable, and `sqlite-vec`'s virtual-table DDL doesn't map cleanly onto an ORM anyway,
  so a thin wrapper of plain SQL + typed Python functions gives more control for less
  code. Tables: `repos(id, url, indexed_at)`, `chunks(id, repo_id, file_path, symbol_type,
  symbol_name, start_line, end_line, signature, source)`, `chunk_vectors` (the `vec0`
  virtual table, one row per chunk keyed by `chunks.id`).
- **`orchestrator/`** — Claude Agent SDK wiring:
  - `AgentDefinition` for `rag-search` (tool: `search_code`, no filesystem access).
  - `AgentDefinition` for `code-explorer` (tools: `Read`, `Grep`, `Glob` only — no
    `Bash`, since the exploration task is read-only structural search, and giving an
    LLM-driven agent shell execution over an arbitrary cloned repo is unnecessary
    attack surface for what this needs to do).
  - Orchestrator prompt: describes the repo/question context, lets Claude route to one
    or both subagents via the `Agent` tool based on their `description` fields — not a
    hardcoded if/else classifier.
- **`api/`** — replaces `POST /repos*` with `POST /ask`. Existing `/health` and `/mcp`
  (still just the Plan 1 `ping` spike) are untouched.
- **`frontend/`** — single page, gitingest-style: URL input, question input, submit,
  answer display with citations. No job-status polling UI (no more `pending/indexing`
  step visible to the user — the first request for a new repo just takes longer).

## Data flow

1. `POST /ask {repo_url, question}`.
2. Look up `repos` by `url`. If missing: run `index_repo()` (Plan 2 pipeline, unchanged,
   `allow_local_paths=False`), embed each chunk with Voyage, insert into `chunks` +
   `chunk_vectors`, insert the `repos` row. If present: reuse as-is — **no automatic
   re-indexing**. A stale index for a repo that changed upstream is an accepted v1
   limitation (see Roadmap); revisiting requires a deliberate `force_reindex` flag,
   not implicit behavior.
3. Run the orchestrator (`query()`) with the question and repo context.
   - Orchestrator decides: RAG-only, explore-only, or both (e.g. RAG surfaces a
     candidate area, explorer confirms exact current line numbers).
   - `code-explorer`, if invoked, triggers a **fresh, on-demand clone** into a new
     temp dir via the unchanged `clone.py`/`cleanup_clone()` pair — never the same
     directory used at index time, never persisted. Its `Read`/`Grep`/`Glob` access
     is scoped to that temp dir so it cannot read anything outside the cloned repo.
     The temp dir is removed once the orchestrator's turn completes, in a `finally`.
4. Orchestrator returns a synthesized answer with file:line citations; `POST /ask`
   returns it to the frontend.

## Error handling

Extends the existing `IndexingError` hierarchy (unchanged) with orchestration-level
failures:

| Failure | Behavior |
|---|---|
| Any `IndexingError` subclass during first-time indexing | `POST /ask` returns 4xx with the typed error message; nothing is partially stored |
| Orchestrator/subagent raises or times out | `POST /ask` returns 502 with a generic "couldn't answer" message; logged with full detail server-side |
| `code-explorer` re-clone fails (network blip, etc.) | Orchestrator falls back to RAG-only answer if it already has partial results; otherwise surfaces the clone error |
| Low-confidence RAG result (few/low-similarity matches) | Orchestrator is prompted to fall back to `code-explorer` rather than answering from weak context — mitigates the risk of the router picking the wrong subagent for an ambiguous question |

## Security

Unchanged from the original doc's model, plus:
- `code-explorer`'s tool set is capability-limited by design (`Read`/`Grep`/`Glob`
  only, no `Bash`, no `Write`/`Edit`) — it can inspect the clone, not modify it or
  execute anything in it.
- The re-clone for exploration reuses `clone.py` unchanged, so it inherits the same
  host allowlist / size cap / timeout / URL-injection defenses already hardened in
  Plan 2. `allow_local_paths` stays `False` here, same rule as the rest of the
  real endpoints.

## Testing

- Unit: `store/` functions against a temp SQLite file (insert/query chunks and
  vectors, cosine similarity ranking correctness).
- Unit: orchestrator subagent definitions — mock the Agent SDK's `query()` to assert
  the right tools/description are wired, without burning real API calls.
- Integration: `POST /ask` end-to-end against a small fixture repo, with Voyage and
  Claude calls mocked (no quota burned in CI) — asserts indexing happens once, is
  reused on a second call, and citations resolve to real file:line ranges.
- Manual/documented-only: real orchestrator routing behavior (does it pick RAG vs.
  explorer sensibly) is validated by hand against a handful of real questions before
  demoing — LLM routing correctness isn't practically unit-testable, and the design
  doc says so explicitly rather than pretending otherwise.

## Roadmap (explicitly deferred)

- **Phase 2 — MCP**: wire `index_repo`/`search_code`/`ask_repo` (or an equivalent
  `ask` tool) onto the existing `mcp_server/server.py` `mcp` object, reusing the same
  orchestrator internals, so Claude Desktop/other MCP clients can consume this project
  too. Explicitly sequenced after phase 1 ships, not in parallel.
- Force re-index / cache invalidation for repos that changed upstream.
- Caching `code-explorer` results (currently a fresh clone + fresh tool-use loop per
  request that needs it — accepted latency/cost tradeoff for v1, revisit if the
  explorer path turns out to be a majority of traffic).
- Multi-language support, rate limiting, richer frontend — unchanged from the
  original doc's roadmap.

## Related, unchanged work

Plan 2's `coderag_mcp/indexing/` module is consumed as-is by this design's indexing
step and by the on-demand re-clone for `code-explorer`. No changes to `clone.py`,
`chunker.py`, `pipeline.py`, or `models.py` are required by this design.
