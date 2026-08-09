---
title: CodeRAG-MCP — Indexing pipeline (clone → tree-sitter → chunks)
status: approved
date: 2026-08-08
---

# Indexing pipeline — Design

## Summary

Plan 2 of the CodeRAG-MCP build order (see
`docs/superpowers/specs/2026-08-08-coderag-mcp-backend-design.md`). Implements the
clone → parse → chunk stage of the indexing pipeline as a pure, dependency-free-of-DB
function: given a public repo URL, produce a list of AST-aware code chunks (function,
class, method) with metadata. No HTTP endpoint, no database, no embeddings — those are
later plans. This stage is built to production quality, not as throwaway/mock work: the
git clone, tree-sitter parsing, and security limits implemented here are what ships,
unchanged, when the REST/MCP layer is wired on top of it in later plans.

## Scope

In scope:
- Repo cloning with host allowlist, shallow clone, size cap, timeout.
- Python-only tree-sitter parsing and chunk extraction (function/class/method level).
- Typed error handling for job-level failures; non-fatal per-file failures.
- Unit and integration tests against a local git fixture repo (no network dependency).

Out of scope (later plans):
- HTTP endpoint (`POST /repos`) and job status persistence.
- Embeddings (Voyage `voyage-code-3`) and Postgres/pgvector storage.
- Configurable limits via `pydantic-settings` (hardcoded constants for now — see
  Rationale below).
- Non-Python languages.

## Architecture

```
coderag_mcp/indexing/
    __init__.py
    models.py      # Chunk dataclass
    clone.py        # clone_repo(url) -> Path
    chunker.py       # chunk_file(path, repo_url) -> list[Chunk]
    pipeline.py      # index_repo(url) -> list[Chunk]  (orchestrates the above)
```

`index_repo()` is the single public entry point. It has no knowledge of HTTP, jobs, or
persistence — Plan 3 (embeddings) calls it directly and feeds its output to the
embedding client; a later plan wraps it behind `POST /repos` and the `index_repo` MCP
tool. The mounting/lifespan wiring in `api/main.py` is untouched by this plan.

## Components

### `models.py` — `Chunk`

```python
@dataclass
class Chunk:
    repo_url: str
    file_path: str            # relative to repo root
    symbol_type: str          # "function" | "class" | "method"
    symbol_name: str
    start_line: int
    end_line: int
    signature: str            # e.g. "def foo(a: int, b: str) -> bool:"
    source: str               # full source text of the chunk, for embedding
    parent_class: str | None  # set when symbol_type == "method"
```

### `clone.py` — `clone_repo(url: str) -> Path`

- Validates the URL's host against a hardcoded allowlist (`github.com`, `gitlab.com`).
  Rejects any other host, bare IPs, and `localhost` — mitigates SSRF.
- Runs `git clone --depth=1 <url> <tmpdir>` via `subprocess.run(..., timeout=CLONE_TIMEOUT_S)`.
- After cloning, measures the working tree size; if it exceeds `MAX_REPO_SIZE_MB`,
  deletes the tmpdir and raises.
- Returns the `Path` to the cloned tmpdir. Caller owns cleanup.
- Raises typed exceptions (see Error handling) — never returns a partial/invalid path.

### `chunker.py` — `chunk_file(path: Path, repo_url: str) -> list[Chunk]`

- Parses one `.py` file with `tree-sitter` + `tree-sitter-python`.
- Walks the syntax tree:
  - Top-level `function_definition` → one `"function"` chunk.
  - `class_definition` → one `"class"` chunk (class signature + docstring, not the
    full body) **plus** one `"method"` chunk per method defined inside it, each with
    `parent_class` set to the class name.
- On parse failure for a file (malformed syntax, encoding error): logs a warning and
  returns `[]` for that file. Never raises — per-file failures are non-fatal.

### `pipeline.py` — `index_repo(repo_url: str) -> list[Chunk]`

1. `clone_repo(repo_url)` → tmpdir `Path`.
2. `tmpdir.rglob("*.py")` → file list. If count exceeds `MAX_FILE_COUNT`, clean up and
   raise before parsing anything (avoids burning time on an oversized job that will be
   rejected anyway).
3. Enforces a wall-clock timeout covering clone + parse together
   (`PIPELINE_TIMEOUT_S`) — separate from the backend design spec's ~5 min budget,
   which also covers embeddings added in Plan 3.
4. Runs `chunk_file()` per file, accumulating results.
5. `finally`: removes the tmpdir, whether the pipeline succeeded or raised.
6. Returns the accumulated `list[Chunk]`.

## Constants (hardcoded for this plan)

```python
ALLOWED_HOSTS = {"github.com", "gitlab.com"}
MAX_REPO_SIZE_MB = 200
CLONE_TIMEOUT_S = 60
PIPELINE_TIMEOUT_S = 120   # clone + parse combined
MAX_FILE_COUNT = 500
```

**Rationale for hardcoding (not `pydantic-settings` yet):** these are internal
implementation limits for a pipeline stage with no external caller yet (no HTTP
endpoint in this plan). Promoting them to configurable settings happens naturally when
the REST/MCP layer is wired on in a later plan and an operator actually needs to tune
them per deployment — doing it now would be speculative config with no consumer.

## Error handling

| Failure | Level | Behavior |
|---|---|---|
| Host not in allowlist | job | `InvalidRepoURLError`, raised before any I/O |
| `git clone` exceeds `CLONE_TIMEOUT_S` | job | `CloneTimeoutError`, tmpdir cleaned up |
| Repo size exceeds `MAX_REPO_SIZE_MB` | job | `RepoTooLargeError`, tmpdir cleaned up |
| `.py` file count exceeds `MAX_FILE_COUNT` | job | `TooManyFilesError`, tmpdir cleaned up |
| Pipeline exceeds `PIPELINE_TIMEOUT_S` | job | `PipelineTimeoutError`, tmpdir cleaned up |
| Single file fails to parse | file | logged warning, `[]` for that file, pipeline continues |

All job-level exceptions are typed subclasses of a common `IndexingError` in
`models.py`, so a future caller (the `/repos` endpoint or `index_repo` MCP tool) can
catch one base type and map it to `status=error` with a message, per the backend
design spec's `pending → indexing → ready/error` job state machine.

## Testing

- **Fixture**: a pytest fixture creates a real local git repo in a tmp dir (`git init`
  + commits) containing `.py` files with known functions, a class with methods, and
  one file with deliberately broken syntax. `clone_repo` clones from this local path
  (a `file://`-style local path bypasses the host allowlist check for tests — the
  allowlist test uses `https://` URLs with invalid hosts directly, without network
  I/O, since the check happens before cloning).
- **`test_clone.py`**: rejects disallowed host, rejects bare IP, rejects `localhost`;
  successful clone of the local fixture repo; size-cap enforcement (fixture repo
  padded past a lowered test threshold); timeout enforcement (mocked slow subprocess).
- **`test_chunker.py`**: known function → correct `Chunk`; class with methods →
  one class chunk + N method chunks with `parent_class` set; broken-syntax file →
  `[]` and a logged warning, no exception.
- **`test_pipeline.py`**: full `index_repo()` against the local fixture repo — asserts
  expected chunk count and spot-checks metadata; file-count cap triggers
  `TooManyFilesError` against a fixture with more files than the (test-lowered) cap.

## Dependencies added

- `tree-sitter` (core library, official bindings)
- `tree-sitter-python` (official Python grammar)

No new dependency for cloning — shells out to the system `git` binary via `subprocess`
(already assumed available, same as any CI/dev environment used to build this repo).
