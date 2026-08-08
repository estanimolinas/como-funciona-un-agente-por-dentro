---
title: CodeRAG-MCP — Code-aware RAG backend served over MCP
status: approved
date: 2026-08-08
---

# CodeRAG-MCP — Backend Design

## Summary

A standalone portfolio project (**new, separate git repo** — not this one) that indexes
public code repositories with AST-aware chunking, stores embeddings in Postgres/pgvector,
and answers questions about the code with citations. The same core logic is exposed both
as a REST API and as an **MCP server** (Streamable HTTP transport), so it can be queried
directly or plugged into any MCP client (Claude Desktop, Claude.ai connectors, etc.).

Target audience: ML/AI engineers reviewing a GitHub portfolio. Goal: demonstrate real
RAG-pipeline judgment (AST chunking over naive line-splitting), current protocol fluency
(MCP), and backend engineering rigor (auth, migrations, CI, security limits) — without
overbuilding scope a solo developer won't finish.

## Why a new repo, not an extension of nanoLoop

nanoLoop (this repo) is an autonomous engineering harness — DeepAgents + LangChain +
OpenShell sandboxing, oriented at running agentic coding tasks. CodeRAG-MCP is a RAG/MCP
backend service, a different problem with a different stack (no LangChain/DeepAgents,
no sandboxed shell execution). Mixing both under one git history would blur the story
each project tells on its own. See `docs/adr/0000-new-repo-not-nanoloop-fork.md` (to be
written in the new repo) for the full rationale.

### What CodeRAG-MCP takes from nanoLoop (patterns, not code)

- **Default-deny, explicit-allowlist security** ([policy.yaml](../../../policy.yaml)):
  the same philosophy that gates nanoLoop's filesystem/network/process access is applied
  to which repo URLs CodeRAG-MCP is willing to clone (host allowlist, size cap, timeout).
- **Job state machine** ([nanoloop/session.py](../../../nanoloop/session.py)): nanoLoop
  tracks tasks as `pending → active → done/blocked`; CodeRAG-MCP tracks indexing jobs as
  `pending → indexing → ready/error`.
- **Model client factory** ([nanoloop/model.py](../../../nanoloop/model.py)): a single
  env-var-configured factory function per external client (Voyage, Claude), rather than
  clients instantiated ad hoc throughout the codebase.
- **Markdown-with-frontmatter documentation** ([nanoloop/memory.py](../../../nanoloop/memory.py)):
  inspires the ADR format (short Markdown files, cross-referenced) rather than one long
  design document.

Not reused: DeepAgents, LangChain, OpenShell as a runtime dependency, the Skills system,
agent session/memory — none of it applies to a non-agentic RAG/MCP service.

## Architecture

```
Browser (React SPA, Vercel)
        │  HTTPS
        ▼
FastAPI service (Render)  ── API key auth (X-API-Key)
        │
        ├── POST /repos          → validates + clones (bg thread) → 202 {job_id}
        ├── GET  /repos/{id}     → status (pending/indexing/ready/error)
        ├── GET  /repos          → list indexed repos
        ├── POST /repos/{id}/ask → RAG: retrieval + answer (Claude Haiku)
        ├── GET  /health         → checks DB connectivity
        └── /mcp                 → MCP server, Streamable HTTP transport
                                    tools: index_repo, search_code, ask_repo
        │
        ▼ (run_in_threadpool — CPU-bound work off the event loop)
Indexing pipeline
        ├── git clone --depth=1 (github.com/gitlab.com only, size + timeout capped)
        ├── tree-sitter parse (Python v1) → chunks (function/class/method + metadata)
        └── Voyage voyage-code-3 → embeddings
        │
        ▼
Postgres + pgvector, HNSW index (Supabase, free tier)
```

Local dev: `docker compose up` (api + postgres). Production: Render (API) + Supabase
(Postgres/pgvector) + Vercel (frontend) — all free tiers, no card required for the core
flow.

## Components

- **`indexing/`** — repo cloning (validated URL, shallow clone, size/timeout limits),
  tree-sitter parser (Python for v1), chunker producing logical units (function/class)
  with metadata (file path, line range, symbol type, signature).
- **`embeddings/`** — Voyage AI client (factory pattern per `model.py`), batch embedding.
- **`store/`** — Postgres/pgvector models (repos, chunks, jobs) and similarity-search
  queries against the HNSW index.
- **`rag/`** — retrieval (top-k chunks) + Claude Haiku prompt, returns answer with
  file:line citations.
- **`mcp_server/`** — exposes `index_repo`, `search_code`, `ask_repo` as MCP tools over
  Streamable HTTP, calling the same internal functions as the REST routers (no duplicated
  logic).
- **`api/`** — FastAPI routers, API key auth, Pydantic schemas, pydantic-settings config,
  `/health`.
- **`frontend/`** — React + Vite + TypeScript SPA: repo URL input → indexing status →
  question box → answer with citations. No routing, no user auth; calls the API with a
  server-side-proxied key.

## Data flow

1. `POST /repos {url}` → URL validated (host allowlist) → row created (`status=pending`)
   → cloning/parsing/embedding runs in a background thread (`run_in_threadpool`, not
   inline on the event loop) → row updated to `ready` or `error` with a message.
2. `POST /repos/{id}/ask {question}` → question embedded → top-k cosine similarity search
   in pgvector → context assembled → Claude Haiku called → answer + chunk citations
   (file:line) returned.
3. The MCP server exposes the same three operations as tools, so an MCP client can index
   and query a repo without going through the REST endpoints directly.

## Security

- Clone URL restricted to `github.com` / `gitlab.com` hosts (rejects IPs, localhost,
  arbitrary hosts — mitigates SSRF).
- `git clone --depth=1` (no history fetched).
- Hard repo size cap (~200MB) checked before parsing; hard job timeout (~5 min) that
  marks the job `error` if exceeded.
- File-count cap per repo during parsing.
- Per-file parse failure (unsupported language, malformed source) is skipped and logged;
  it does not abort the whole indexing job.
- API key required on both REST and MCP endpoints; missing/invalid key → 401.
- Rate limiting is explicitly deferred to v1.1 (see Roadmap) — acceptable for v1 given
  every caller is already authenticated with an API key (no anonymous public traffic).

## Production-readiness (kept in v1 — cheap, high-signal)

- **Alembic** for schema migrations.
- **pydantic-settings** for typed, validated config from env vars.
- **`/health`** endpoint checking Postgres connectivity.
- **Structured JSON logging** with request/job correlation ids.
- **GitHub Actions CI**: pytest, ruff, mypy, coverage badge.

## Testing

- Unit: tree-sitter chunker against fixture files (expected chunk boundaries/metadata);
  pgvector query layer against seeded test data.
- Integration: full index flow against a small real/fixture repo, using a test Postgres
  instance (docker compose or testcontainers).
- API: FastAPI `TestClient` against endpoints, with Voyage/Claude calls mocked (no quota
  burned in CI).
- MCP: at least one test exercising the `/mcp` Streamable HTTP handshake and a tool call
  end-to-end, since this is the least mature/most novel piece of the stack.

## Build order (de-risking)

1. **MCP server spike first**: a minimal server exposing one dummy tool over Streamable
   HTTP, verified against a real MCP client end-to-end. This is the newest, least-proven
   piece of the stack — validate it before investing in the rest.
2. Indexing pipeline (clone → tree-sitter → chunks) with unit tests.
3. Embeddings + pgvector store + HNSW index.
4. RAG endpoint (retrieval + Claude Haiku answer).
5. Wire the real MCP tools to the same internals.
6. Auth, Alembic, settings, health, logging, CI.
7. Minimal React frontend.
8. Deploy (Render + Supabase + Vercel), README (architecture diagram, demo GIF, live
   URL, design-decisions section), ADRs.

## Roadmap (explicitly out of scope for v1)

- RQ + Redis for real background job queueing (v1 uses in-process background threads).
- Multi-language support beyond Python (JS/TS next, via additional tree-sitter grammars).
- Rate limiting per API key (slowapi).
- IVFFlat vs. HNSW re-evaluation at larger data volumes.
- Richer frontend (multi-repo comparison, syntax-highlighted citations, etc.).

## Related, explicitly decoupled work

Adapting nanoLoop's `model.py` to use Anthropic directly (`ChatAnthropic` via
`langchain-anthropic`) instead of OpenRouter is a separate, small task, tracked
independently. It does not block CodeRAG-MCP, and CodeRAG-MCP does not depend on nanoLoop
being adapted first or being used as its build tool.
