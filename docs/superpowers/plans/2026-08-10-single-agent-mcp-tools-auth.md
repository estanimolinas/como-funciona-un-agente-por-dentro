# Single-Agent Orchestrator, Real MCP Tools, and Auth/Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add API key auth to `/ask` and `/mcp`, collapse the dual-path orchestrator
(`rag-search`/`code-explorer` subagents) into a single agent with direct tool access,
wire real MCP tools (`index_repo`, `search_code`, `ask_repo`) onto the `mcp` object, and
harden the deferred tech debt from the dual-path-orchestrator plan's whole-branch
review (blocking I/O on the event loop, per-request SQLite connections, a new Voyage
client per call, duplicated transaction-ownership logic) — per
`docs/superpowers/specs/2026-08-10-single-agent-mcp-tools-auth-design.md`.

**Architecture:** `api/` (`/ask`) and `mcp_server/` (`/mcp`) stay thin adapters over one
domain core (`orchestrator/`, `store/`, `embeddings/`) — neither duplicates the other's
indexing/answering logic. Each transport holds its own shared, lazily-opened-once SQLite
connection (FastAPI's via `app.state`/lifespan, the MCP server's via `MCPServer`'s own
`lifespan=` parameter and `Context` injection) guarded by an `asyncio.Lock`, with all
blocking work (git clone, Voyage HTTP calls, sqlite reads/writes) run through
`asyncio.to_thread`.

**Tech Stack:** FastAPI, Starlette middleware, `mcp==2.0.0`, `claude-agent-sdk==0.2.95`,
`apsw`, `voyageai`, `pydantic-settings`.

## Global Constraints

- `api/` and `mcp_server/` are thin adapters; all indexing/search/answer logic stays in
  `orchestrator/`, `store/`, `embeddings/` — no logic duplicated between the two
  transports.
- Every blocking call (git clone, Voyage HTTP, sqlite read/write) runs through
  `asyncio.to_thread` — directly for non-DB work (git clone), or via
  `store.db.run_db_sync` (lock + `asyncio.to_thread`) for anything touching a shared
  SQLite connection. Never call blocking I/O directly on the event loop.
- `/ask`'s shared connection and `/mcp`'s shared connection are two separate Python
  objects (one per transport, each opened once and reused, each with its own lock) —
  not one connection threaded across both transports. Both still eliminate the
  per-request "reopen + reload sqlite-vec extension" cost this plan is fixing.
- `CODERAG_API_KEY` empty/unset (the default) means auth is disabled — required so
  existing and new tests don't need to set a key everywhere. Never make auth
  fail-closed on an empty key; that would make every un-configured deployment 401 on
  everything.
- No change to `index_and_store_repo`'s idempotency-by-URL contract, `IndexingError`
  hierarchy, or `allow_local_paths=False` as the only production default — those are
  Plan 2/dual-path-orchestrator constraints and stay in force.
- `mcp==2.0.0` and `claude-agent-sdk==0.2.95`'s actual installed APIs may not match
  training-data assumptions (the established gotcha documented in this repo's
  `CLAUDE.md` and `coderag_mcp/orchestrator/_mcp_compat.py`). Every task below that
  touches either SDK has already been verified against the installed version while
  writing this plan; if your environment's installed version differs, adapt the task's
  code to match and note the discrepancy in your task report.

---

### Task 1: Promote hardcoded indexing constants to settings

**Files:**
- Modify: `coderag_mcp/config.py`
- Modify: `coderag_mcp/indexing/clone.py`
- Modify: `coderag_mcp/indexing/pipeline.py`
- Modify: `tests/indexing/test_clone.py`
- Modify: `tests/indexing/test_pipeline.py`

**Interfaces:**
- Produces: `Settings` gains `allowed_hosts: list[str]`, `max_repo_size_mb: int`,
  `clone_timeout_s: int`, `max_file_count: int`, `pipeline_timeout_s: int` (in
  `coderag_mcp/config.py`). No later task consumes these directly — this task is
  self-contained.

- [ ] **Step 1: Add the settings fields**

Edit `coderag_mcp/config.py`:

```python
"""Typed application settings, loaded from environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "coderag-mcp"
    public_host: str = "127.0.0.1"
    voyage_api_key: str = ""
    sqlite_db_path: str = "coderag.db"
    allowed_hosts: list[str] = ["github.com", "gitlab.com"]
    max_repo_size_mb: int = 200
    clone_timeout_s: int = 60
    max_file_count: int = 500
    pipeline_timeout_s: int = 120


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Read settings in `clone.py` instead of module constants**

Edit `coderag_mcp/indexing/clone.py`. Replace the `ALLOWED_HOSTS`/`MAX_REPO_SIZE_MB`/
`CLONE_TIMEOUT_S` module constants and their three use sites:

```python
"""Validated, capped git cloning for the indexing pipeline."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from coderag_mcp.config import get_settings
from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError, RepoTooLargeError


def _looks_like_scp_style(url: str) -> bool:
    """True for git's SCP-style remote syntax: [user@]host:path (no scheme)."""
    if "://" in url:
        return False
    colon_index = url.find(":")
    if colon_index == -1:
        return False
    slash_index = url.find("/")
    return slash_index == -1 or colon_index < slash_index


def _validate_url(url: str, *, allow_local_paths: bool, allowed_hosts: list[str]) -> None:
    if url.startswith("-"):
        raise InvalidRepoURLError(f"URL must not start with '-': {url!r}")

    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if parsed.hostname not in allowed_hosts:
            raise InvalidRepoURLError(f"host not allowed: {parsed.hostname!r}")
    elif parsed.scheme == "":
        if _looks_like_scp_style(url):
            raise InvalidRepoURLError(f"SCP-style git URLs are not allowed: {url!r}")
        # A bare local filesystem path (used by tests against local fixture
        # repos) never leaves the machine, so there is no SSRF surface to
        # allowlist against — but callers must opt in explicitly, since a
        # future HTTP/MCP caller must never be able to trigger local file
        # disclosure just by passing a path instead of a URL.
        if allow_local_paths:
            return
        raise InvalidRepoURLError(f"local filesystem paths are not allowed: {url!r}")
    else:
        raise InvalidRepoURLError(f"unsupported URL scheme: {parsed.scheme!r}")


def _dir_size_mb(path: Path) -> float:
    total_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total_bytes / (1024 * 1024)


def clone_repo(url: str, *, allow_local_paths: bool = False) -> Path:
    """Clone ``url`` into a fresh temp directory and return the cloned repo's path.

    ``allow_local_paths`` must be explicitly set to ``True`` to permit cloning
    from a bare local filesystem path (used by tests against local fixture
    repos) — callers driven by untrusted input (HTTP/MCP) must leave this
    ``False`` to avoid local file disclosure.

    Raises ``InvalidRepoURLError``, ``CloneTimeoutError``, or ``RepoTooLargeError``
    on failure. The caller owns cleanup via ``cleanup_clone``.
    """
    settings = get_settings()
    _validate_url(url, allow_local_paths=allow_local_paths, allowed_hosts=settings.allowed_hosts)

    tmpdir = Path(tempfile.mkdtemp(prefix="coderag-clone-"))
    dest = tmpdir / "repo"

    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                f"--filter=blob:limit={settings.max_repo_size_mb}m",
                "--",
                url,
                str(dest),
            ],
            check=True,
            capture_output=True,
            timeout=settings.clone_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise CloneTimeoutError(f"clone of {url!r} exceeded {settings.clone_timeout_s}s") from exc
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise InvalidRepoURLError(f"git clone failed for {url!r}: {stderr}") from exc

    size_mb = _dir_size_mb(dest)
    if size_mb > settings.max_repo_size_mb:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RepoTooLargeError(f"{url!r} is {size_mb:.1f}MB, exceeds {settings.max_repo_size_mb}MB cap")

    return dest


def cleanup_clone(cloned_path: Path) -> None:
    """Remove the temp directory tree that clone_repo created for cloned_path."""
    shutil.rmtree(cloned_path.parent, ignore_errors=True)
```

- [ ] **Step 3: Update `test_clone.py`'s constant-monkeypatching tests**

`monkeypatch.setattr(clone_module, "MAX_REPO_SIZE_MB", 0)` no longer works (the
constant is gone) — monkeypatch `get_settings` instead. Edit
`tests/indexing/test_clone.py`, replacing `test_enforces_size_cap`:

```python
def test_enforces_size_cap(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    from coderag_mcp.config import Settings

    monkeypatch.setattr(
        clone_module, "get_settings", lambda: Settings(max_repo_size_mb=0)
    )
    with pytest.raises(RepoTooLargeError):
        clone_repo(str(fixture_repo), allow_local_paths=True)
```

Leave every other test in the file unchanged — they don't touch the promoted constants.

- [ ] **Step 4: Read settings in `pipeline.py` instead of module constants**

Edit `coderag_mcp/indexing/pipeline.py`:

```python
"""Orchestrates clone -> discover .py files -> chunk into the pipeline's public entry point."""
from __future__ import annotations

import logging
import time

from coderag_mcp.config import get_settings
from coderag_mcp.indexing import clone
from coderag_mcp.indexing.chunker import chunk_file
from coderag_mcp.indexing.clone import clone_repo
from coderag_mcp.indexing.models import Chunk, PipelineTimeoutError, TooManyFilesError

logger = logging.getLogger(__name__)


def index_repo(repo_url: str, *, allow_local_paths: bool = False) -> list[Chunk]:
    """Clone, parse, and chunk a repo. Raises IndexingError subclasses on job-level failure."""
    settings = get_settings()
    start = time.monotonic()
    repo_dir = clone_repo(repo_url, allow_local_paths=allow_local_paths)

    try:
        py_files = sorted(repo_dir.rglob("*.py"))
        if len(py_files) > settings.max_file_count:
            raise TooManyFilesError(
                f"{repo_url!r} has {len(py_files)} .py files, exceeds {settings.max_file_count} cap"
            )

        chunks: list[Chunk] = []
        for py_file in py_files:
            if time.monotonic() - start > settings.pipeline_timeout_s:
                raise PipelineTimeoutError(
                    f"indexing {repo_url!r} exceeded {settings.pipeline_timeout_s}s"
                )
            file_path = str(py_file.relative_to(repo_dir))
            try:
                chunks.extend(chunk_file(py_file, repo_url, file_path))
            except Exception as exc:  # noqa: BLE001 - per-file failures must never abort the job
                logger.warning("chunk_file failed for %s: %s", file_path, exc)
        return chunks
    finally:
        clone.cleanup_clone(repo_dir)
```

- [ ] **Step 5: Update `test_pipeline.py`'s constant-monkeypatching tests**

Edit `tests/indexing/test_pipeline.py`, replacing the two tests that monkeypatch module
constants:

```python
def test_index_repo_enforces_file_count_cap(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    from coderag_mcp.config import Settings

    monkeypatch.setattr(pipeline_module, "get_settings", lambda: Settings(max_file_count=1))
    with pytest.raises(TooManyFilesError):
        index_repo(str(fixture_repo), allow_local_paths=True)


def test_index_repo_enforces_pipeline_timeout(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    from coderag_mcp.config import Settings

    monkeypatch.setattr(
        pipeline_module, "get_settings", lambda: Settings(pipeline_timeout_s=-1)
    )
    with pytest.raises(PipelineTimeoutError):
        index_repo(str(fixture_repo), allow_local_paths=True)
```

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (58/58, no regressions — this task only changes where values come from,
not their defaults)

- [ ] **Step 7: Commit**

```bash
git add coderag_mcp/config.py coderag_mcp/indexing/clone.py coderag_mcp/indexing/pipeline.py \
  tests/indexing/test_clone.py tests/indexing/test_pipeline.py
git commit -m "refactor: promote hardcoded indexing constants to pydantic-settings"
```

---

### Task 2: Reuse the Voyage client instead of constructing one per call

**Files:**
- Modify: `coderag_mcp/embeddings/voyage.py`
- Modify: `tests/embeddings/test_voyage.py`

**Interfaces:**
- Produces: `embed_batch(texts, *, input_type="document")` — signature unchanged, only
  the internal client lifecycle changes. No later task depends on the new internals.

- [ ] **Step 1: Write the failing test**

Edit `tests/embeddings/test_voyage.py`, adding:

```python
def test_embed_batch_reuses_client_across_calls():
    fake_result = MagicMock(embeddings=[[0.1, 0.2]])
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.return_value = fake_result

        embed_batch(["a"], input_type="document")
        embed_batch(["b"], input_type="document")

        mock_client_cls.assert_called_once()
```

This needs a per-test reset of the module-level client singleton, since the singleton
otherwise persists across tests in the same process. Add a `conftest.py` fixture — check
whether `tests/embeddings/` already has one:

```bash
ls tests/embeddings/conftest.py 2>&1
```

If it doesn't exist, create `tests/embeddings/conftest.py`:

```python
import pytest

from coderag_mcp.embeddings import voyage


@pytest.fixture(autouse=True)
def _reset_voyage_client():
    voyage._client = None
    yield
    voyage._client = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/embeddings/test_voyage.py::test_embed_batch_reuses_client_across_calls -v`
Expected: FAIL (`mock_client_cls.assert_called_once()` fails — currently called twice,
once per `embed_batch` call)

- [ ] **Step 3: Make the client a lazily-initialized module-level singleton**

Edit `coderag_mcp/embeddings/voyage.py`:

```python
"""Voyage AI embedding client for code chunks."""
from __future__ import annotations

import voyageai

from coderag_mcp.config import get_settings

MODEL = "voyage-code-3"

_client: voyageai.Client | None = None


def _get_client() -> voyageai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


def embed_batch(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    """Embed texts with voyage-code-3.

    voyage-code-3 is an asymmetric model: pass input_type="document" when embedding
    the indexed corpus (the default, matching every existing indexing call site) and
    input_type="query" when embedding a search query - using the wrong side degrades
    retrieval quality without raising any error.
    """
    client = _get_client()
    result = client.embed(texts, model=MODEL, input_type=input_type)
    return result.embeddings
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `./.venv/bin/pytest tests/embeddings/test_voyage.py -v`
Expected: PASS (all 3 tests, including the two pre-existing ones — they still patch
`coderag_mcp.embeddings.voyage.voyageai.Client` and now also benefit from the autouse
fixture resetting `_client` between tests)

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (58/58 + 1 new = 59/59)

- [ ] **Step 6: Commit**

```bash
git add coderag_mcp/embeddings/voyage.py tests/embeddings/test_voyage.py
git commit -m "perf: reuse the Voyage client instead of constructing one per embed_batch call"
```

---

### Task 3: Dedupe transaction-ownership logic into a shared helper

**Files:**
- Modify: `coderag_mcp/store/db.py`
- Modify: `coderag_mcp/store/chunks.py`
- Modify: `coderag_mcp/store/repos.py`
- Modify: `coderag_mcp/orchestrator/indexing_service.py`
- Test: `tests/store/test_db.py`

**Interfaces:**
- Produces: `_APSWWrapper.in_transaction: bool` (property) and
  `transaction(conn) -> AbstractContextManager[None]`, both in `coderag_mcp/store/db.py`.
  Task 4 imports `transaction` is NOT needed there (Task 4 doesn't touch transactions,
  only connection lifecycle) — this task's consumers are exactly the three files above.

- [ ] **Step 1: Write the failing test for the new primitives**

Add to `tests/store/test_db.py`:

```python
def test_transaction_commits_on_success(tmp_path):
    from coderag_mcp.store.db import get_connection, init_schema, transaction

    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)

    with transaction(conn):
        conn.execute("INSERT INTO repos (url) VALUES (?)", ("https://github.com/a/b",))

    row = conn.execute("SELECT url FROM repos").fetchone()
    assert row[0] == "https://github.com/a/b"


def test_transaction_rolls_back_on_exception(tmp_path):
    from coderag_mcp.store.db import get_connection, init_schema, transaction

    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)

    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO repos (url) VALUES (?)", ("https://github.com/a/b",))
            raise RuntimeError("boom")

    row = conn.execute("SELECT COUNT(*) FROM repos").fetchone()
    assert row[0] == 0


def test_transaction_nested_call_does_not_commit_or_rollback_early(tmp_path):
    """A transaction() opened while one is already active must not touch it -
    only the outermost transaction() call owns commit/rollback."""
    from coderag_mcp.store.db import get_connection, init_schema, transaction

    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)

    with transaction(conn):
        with transaction(conn):
            conn.execute("INSERT INTO repos (url) VALUES (?)", ("https://github.com/a/b",))
        # Inner transaction() exited without committing - row must still be
        # visible on this same connection (uncommitted writes are visible to
        # the same connection) but only the outer exit actually commits.
        assert conn.in_transaction is True

    assert conn.in_transaction is False
    row = conn.execute("SELECT COUNT(*) FROM repos").fetchone()
    assert row[0] == 1
```

Add `import pytest` to the top of `tests/store/test_db.py` if not already present (check
the file first).

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/store/test_db.py -v`
Expected: FAIL with `ImportError` / `AttributeError` (`transaction`/`in_transaction`
don't exist yet)

- [ ] **Step 3: Add `in_transaction` property and `transaction()` context manager**

Edit `coderag_mcp/store/db.py`. Add `from contextlib import contextmanager` and
`Iterator` to the imports, add the property to `_APSWWrapper`, and add the module-level
function after the class definitions:

```python
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

import apsw
```

Inside `_APSWWrapper`, after `close()`:

```python
    @property
    def in_transaction(self) -> bool:
        """True if a transaction is currently active on this connection."""
        return self._conn.in_transaction
```

After `_CursorWrapper` (before `get_connection`):

```python
@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a block atomically, committing on success and rolling back on exception.

    If a transaction is already active on ``conn`` (e.g. this is a nested call from
    a caller that already opened one), this is a no-op wrapper: it neither begins nor
    commits/rolls back - only the outermost ``transaction()`` call for a given
    connection owns the transaction's lifecycle. This lets store-layer functions
    (``create_repo``, ``insert_chunks``) be called either standalone or as part of a
    larger caller-managed transaction (``index_and_store_repo``) without duplicating
    "am I the owner?" logic at each call site.
    """
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.begin()
    try:
        yield
        if owns_transaction:
            conn.commit()
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/store/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Use `transaction()` in `store/repos.py`**

Replace `coderag_mcp/store/repos.py`'s `create_repo`:

```python
"""Repo row lookups/creation, keyed by URL."""
from __future__ import annotations

import sqlite3

from coderag_mcp.store.db import transaction


def get_repo_id_by_url(conn: sqlite3.Connection, url: str) -> int | None:
    row = conn.execute("SELECT id FROM repos WHERE url = ?", (url,)).fetchone()
    return row[0] if row else None


def create_repo(conn: sqlite3.Connection, url: str) -> int:
    with transaction(conn):
        cursor = conn.execute("INSERT INTO repos (url) VALUES (?)", (url,))
    assert cursor.lastrowid is not None
    return cursor.lastrowid
```

- [ ] **Step 6: Use `transaction()` in `store/chunks.py`**

Replace `coderag_mcp/store/chunks.py`'s `insert_chunks` body (leave `ChunkResult`,
`_serialize`, and `search_chunks` unchanged):

```python
def insert_chunks(
    conn: sqlite3.Connection,
    repo_id: int,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must be the same length")

    with transaction(conn):
        for chunk, embedding in zip(chunks, embeddings):
            cursor = conn.execute(
                """
                INSERT INTO chunks
                    (repo_id, file_path, symbol_type, symbol_name, start_line, end_line,
                     signature, source, parent_class)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo_id,
                    chunk.file_path,
                    chunk.symbol_type,
                    chunk.symbol_name,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.signature,
                    chunk.source,
                    chunk.parent_class,
                ),
            )
            conn.execute(
                "INSERT INTO chunk_vectors (chunk_id, repo_id, embedding) VALUES (?, ?, ?)",
                (cursor.lastrowid, repo_id, _serialize(embedding)),
            )
```

Add `from coderag_mcp.store.db import transaction` to its imports.

- [ ] **Step 7: Use `transaction()` in `orchestrator/indexing_service.py`**

Replace `coderag_mcp/orchestrator/indexing_service.py` entirely:

```python
"""Idempotent glue: index a repo (Plan 2 pipeline) and store its embedded chunks."""
from __future__ import annotations

import sqlite3

import apsw

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.indexing.pipeline import index_repo
from coderag_mcp.store import chunks as chunk_store
from coderag_mcp.store import repos as repo_store
from coderag_mcp.store.db import transaction


def index_and_store_repo(conn: sqlite3.Connection, repo_url: str) -> int:
    """Return the repo's id, indexing and embedding it first if not already stored."""
    existing_id = repo_store.get_repo_id_by_url(conn, repo_url)
    if existing_id is not None:
        return existing_id

    extracted = index_repo(repo_url, allow_local_paths=False)

    # Embed chunks if any exist (before creating repo, so embedding failures don't poison the DB)
    embeddings = None
    if extracted:
        embeddings = embed_batch([chunk.source for chunk in extracted])

    try:
        with transaction(conn):
            repo_id = repo_store.create_repo(conn, repo_url)
            if extracted:
                chunk_store.insert_chunks(conn, repo_id, extracted, embeddings)
    except apsw.ConstraintError:
        # Concurrent call created the row first; transaction() already rolled back
        # this attempt - look up the winner's repo_id instead.
        repo_id = repo_store.get_repo_id_by_url(conn, repo_url)
        assert repo_id is not None
        return repo_id

    return repo_id
```

This removes the manual `conn.begin()`/`conn.commit()`/`conn.rollback()` calls entirely
— `transaction()` (via `create_repo`'s and `insert_chunks`'s own now-nested
`transaction()` calls) owns the whole operation atomically, and `create_repo`'s
`apsw.ConstraintError` propagates out through both nested `transaction()` context
managers (each rolling back correctly per Step 3's "only the owner rolls back" rule)
before being caught here.

- [ ] **Step 8: Run the full suite**

Run: `./.venv/bin/pytest -v`

Pay special attention to
`tests/orchestrator/test_indexing_service.py::test_concurrent_calls_recover_from_real_constraint_error`
— it asserts the exact recovery behavior this refactor must preserve byte-for-byte
(a real `apsw.ConstraintError` from a genuine UNIQUE violation must still be caught and
recovered from). If it fails, re-read that test's docstring before changing anything —
it explains exactly which calls are real vs. mocked and why.

Expected: PASS (59/59)

- [ ] **Step 9: Commit**

```bash
git add coderag_mcp/store/db.py coderag_mcp/store/chunks.py coderag_mcp/store/repos.py \
  coderag_mcp/orchestrator/indexing_service.py tests/store/test_db.py
git commit -m "refactor: dedupe transaction-ownership logic into store.db.transaction()"
```

---

### Task 4: Shared SQLite connection + blocking-I/O offload for `/ask`

**Files:**
- Create: `coderag_mcp/api/deps.py`
- Modify: `coderag_mcp/store/db.py`
- Modify: `coderag_mcp/api/main.py`
- Modify: `coderag_mcp/api/ask_route.py`
- Modify: `coderag_mcp/orchestrator/ask.py`
- Modify: `coderag_mcp/orchestrator/tools.py`
- Modify: `tests/api/test_ask_route.py`
- Test: `tests/store/test_db.py` (add `run_db_sync` test)

**Interfaces:**
- Consumes: `transaction` (Task 3, unaffected by this task), `get_connection`,
  `init_schema` (existing, `store/db.py`).
- Produces: `store.db.db_lock: asyncio.Lock`, `store.db.run_db_sync(fn, *args,
  **kwargs) -> Awaitable[Any]` (in `coderag_mcp/store/db.py`). `api.deps.get_db_conn(request:
  Request) -> sqlite3.Connection` (in `coderag_mcp/api/deps.py`) — a FastAPI dependency
  reading `request.app.state.db_conn`. Task 5 imports `get_db_conn` from
  `coderag_mcp.api.deps` to compose it with the auth dependency on the same route; Task
  7 does **not** reuse this — the MCP transport gets its own connection via `MCPServer`'s
  `lifespan=` (see Task 7).

- [ ] **Step 1: Write the failing test for `run_db_sync`**

Add to `tests/store/test_db.py`:

```python
async def test_run_db_sync_offloads_to_a_thread_and_returns_the_result():
    import threading

    from coderag_mcp.store.db import run_db_sync

    caller_thread = threading.current_thread()
    seen_thread = {}

    def _work(x, y):
        seen_thread["thread"] = threading.current_thread()
        return x + y

    result = await run_db_sync(_work, 2, 3)

    assert result == 5
    assert seen_thread["thread"] is not caller_thread
```

Add `import pytest` and `pytestmark = pytest.mark.asyncio` near the top of
`tests/store/test_db.py` if not already present for async tests in this file (check
first — other test files in this project use `@pytest.mark.asyncio` per-function
instead; match whichever convention `tests/store/test_db.py` doesn't already have by
using `@pytest.mark.asyncio` on this one function, since the rest of the file's tests
are synchronous).

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/store/test_db.py::test_run_db_sync_offloads_to_a_thread_and_returns_the_result -v`
Expected: FAIL (`ImportError: cannot import name 'run_db_sync'`)

- [ ] **Step 3: Add `db_lock` and `run_db_sync` to `store/db.py`**

Add to `coderag_mcp/store/db.py`'s imports: `import asyncio`, `from collections.abc
import Callable`, and `from typing import TypeVar` (`Any` is already imported in this
file). Add near the top, after `EMBEDDING_DIM`:

```python
db_lock = asyncio.Lock()

_T = TypeVar("_T")


async def run_db_sync(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Run a blocking, DB-touching callable off the event loop, serialized by db_lock.

    apsw connections aren't safe for concurrent use from multiple threads at once;
    asyncio.to_thread alone would let several ThreadPoolExecutor workers touch the
    same shared connection simultaneously. db_lock is acquired here (on the event
    loop, before the thread is spawned) so only one such call runs at a time.
    """
    async with db_lock:
        return await asyncio.to_thread(fn, *args, **kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/store/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Write `coderag_mcp/api/deps.py`**

```python
"""FastAPI dependencies shared across routes."""
from __future__ import annotations

import sqlite3

from fastapi import Request


def get_db_conn(request: Request) -> sqlite3.Connection:
    """The shared SQLite connection opened once at app startup (see api/main.py's
    lifespan) - never call store.db.get_connection() per-request in a route."""
    return request.app.state.db_conn
```

- [ ] **Step 6: Wire the shared connection into `api/main.py`'s lifespan**

Edit `coderag_mcp/api/main.py`:

```python
"""FastAPI application entrypoint, with the MCP server mounted at /mcp.

Note on adapting to the installed `mcp` SDK (2.0.0):

- `MCPServer.streamable_http_app()` defaults to serving its own routes under
  the path "/mcp" *within* the app it returns. Mounting that app at "/mcp"
  in the outer FastAPI app (as the brief's example did) would have produced
  "/mcp/mcp". We pass ``streamable_http_path="/"`` so the inner app serves
  at its own root, and mount that at "/mcp" here instead.
- The returned app is a plain `starlette.applications.Starlette` instance
  with no public `.lifespan` attribute/callable. The actual lifespan hook
  (which starts/stops the `StreamableHTTPSessionManager` for session
  bookkeeping) lives at `app.router.lifespan_context`, an async context
  manager factory. We call that directly from our own lifespan instead of
  the brief's `mcp_app.lifespan(mcp_app)`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from coderag_mcp.api.ask_route import router as ask_router
from coderag_mcp.config import get_settings
from coderag_mcp.mcp_server.server import mcp
from coderag_mcp.store.db import get_connection, init_schema

settings = get_settings()

mcp_app = mcp.streamable_http_app(streamable_http_path="/", host=settings.public_host)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_conn = get_connection(settings.sqlite_db_path)
    init_schema(app.state.db_conn)
    try:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    finally:
        app.state.db_conn.close()


app = FastAPI(title="CodeRAG-MCP", lifespan=lifespan)
app.mount("/mcp", mcp_app)
app.include_router(ask_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 7: Offload blocking work in `api/ask_route.py`, using the shared connection**

Replace `coderag_mcp/api/ask_route.py` entirely:

```python
"""POST /ask: index-on-first-use, then route the question through the orchestrator."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.schemas import AskRequest, AskResponse
from coderag_mcp.indexing.models import IndexingError
from coderag_mcp.orchestrator.ask import ask as run_ask
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.store.db import run_db_sync

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask_endpoint(
    request: AskRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> AskResponse:
    try:
        repo_id = await run_db_sync(index_and_store_repo, conn, request.repo_url)
    except IndexingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - e.g. Voyage embedding failures
        raise HTTPException(
            status_code=502, detail="Could not index the repository."
        ) from exc

    try:
        answer = await run_ask(conn, repo_id, request.repo_url, request.question)
    except IndexingError as exc:
        # ask() re-clones the repo on every call (see orchestrator/ask.py); this
        # can fail with the same errors as the initial index even on a cache hit.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - any other orchestrator/subagent failure
        raise HTTPException(
            status_code=502, detail="Could not answer the question."
        ) from exc

    return AskResponse(answer=answer)
```

Note this task deliberately runs `index_and_store_repo` (clone + embed + DB writes) as
one `run_db_sync` call, holding `db_lock` for its whole duration (including the git
clone) rather than splitting the lock more finely — indexing only happens once per repo
(idempotent), so this is an acceptable simplification for this project's scale, not a
real pool. `run_ask` is *not* wrapped in `run_db_sync` here — Step 8 makes its own
blocking calls (`fresh_clone`, the `search_code` tool) self-offloading instead, since
`run_ask`'s `query()` call is itself already a proper async generator (non-blocking) and
must not be run inside `asyncio.to_thread`.

- [ ] **Step 8: Offload the clone/cleanup calls inside `orchestrator/ask.py`**

`fresh_clone` (in `agents.py`) is a `@contextmanager`-decorated generator — a plain
`with fresh_clone(repo_url):` can't be offloaded as a unit, since the `query()` call
inside the block is itself async and must stay on the event loop, awaited normally. So
this task bypasses the context-manager wrapper and calls the two blocking functions it
wraps (`clone.clone_repo`/`clone.cleanup_clone`) directly via `asyncio.to_thread`, with
an explicit `try`/`finally` in place of the `with` block.

Edit `coderag_mcp/orchestrator/ask.py`:

```python
"""Ties the two subagents together behind a single ask() call."""
from __future__ import annotations

import asyncio
import sqlite3

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from coderag_mcp.indexing import clone
from coderag_mcp.orchestrator.agents import CODE_EXPLORER, RAG_SEARCH
from coderag_mcp.orchestrator.tools import build_search_server


async def ask(conn: sqlite3.Connection, repo_id: int, repo_url: str, question: str) -> str:
    search_server = build_search_server(conn, repo_id)

    repo_dir = await asyncio.to_thread(clone.clone_repo, repo_url, allow_local_paths=False)
    try:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            allowed_tools=["Agent"],
            mcp_servers={"search": search_server},
            agents={"rag-search": RAG_SEARCH, "code-explorer": CODE_EXPLORER},
        )

        answer_parts: list[str] = []
        async for message in query(prompt=question, options=options):
            if not isinstance(message, AssistantMessage):
                continue
            for block in message.content:
                if isinstance(block, TextBlock):
                    answer_parts.append(block.text)

        return "".join(answer_parts)
    finally:
        await asyncio.to_thread(clone.cleanup_clone, repo_dir)
```

(This still references `RAG_SEARCH`/`CODE_EXPLORER`/`allowed_tools=["Agent"]` —
Task 6 replaces those; don't jump ahead. This task's job is only the offload.)

`fresh_clone` in `coderag_mcp/orchestrator/agents.py` is now unused by `ask.py` (and by
anything else in this codebase) — leave it in place in this task regardless; Task 6
removes it as part of its own rewrite of `agents.py`, since deleting it here would be an
unrelated-to-this-task's-purpose edit to a file this task doesn't otherwise touch.

- [ ] **Step 9: Offload the `search_code` tool's blocking work in `orchestrator/tools.py`**

Edit `coderag_mcp/orchestrator/tools.py`:

```python
"""The search_code custom tool, exposed to the rag-search subagent as an in-process
MCP server per the Claude Agent SDK's custom-tool mechanism.

Note on the installed claude-agent-sdk API (0.2.95): `create_sdk_mcp_server` returns
an `McpSdkServerConfig` (fields: type, name, instance) whose `instance` is a
low-level `mcp.server.Server` object — it does NOT expose a `.tools` dict, so a
registered tool's handler cannot be reached from the returned server config. To keep
the tool callable directly testable, `_build_search_tool` constructs the
`SdkMcpTool` (which does have a `.handler` attribute) separately, and
`build_search_server` wraps it for `create_sdk_mcp_server`.

Also patches `mcp.server.Server` via `_mcp_compat.patch_mcp_server()` before calling
`create_sdk_mcp_server` - see that module's docstring for why: `create_sdk_mcp_server`
is written against the mainstream `mcp` SDK's low-level `Server` API, which this repo's
pinned `mcp==2.0.0` doesn't have.
"""
from __future__ import annotations

import sqlite3

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.orchestrator._mcp_compat import patch_mcp_server
from coderag_mcp.store.chunks import search_chunks
from coderag_mcp.store.db import run_db_sync


def _build_search_tool(conn: sqlite3.Connection, repo_id: int) -> SdkMcpTool:
    def _search(query_text: str, top_k: int):
        query_embedding = embed_batch([query_text], input_type="query")[0]
        return search_chunks(conn, repo_id, query_embedding, top_k=top_k)

    @tool(
        "search_code",
        "Semantic search over the indexed repo's code chunks. Returns the top "
        "matching functions/classes/methods with file path, line range, and source.",
        {"query": str, "top_k": int},
    )
    async def search_code(args: dict) -> dict:
        top_k = args.get("top_k", 5)
        results = await run_db_sync(_search, args["query"], top_k)

        if not results:
            text = "No matches found."
        else:
            text = "\n\n".join(
                f"{r.file_path}:{r.start_line}-{r.end_line} "
                f"({r.symbol_type} {r.symbol_name})\n{r.signature}\n{r.source}"
                for r in results
            )
        return {"content": [{"type": "text", "text": text}]}

    return search_code


def build_search_server(conn: sqlite3.Connection, repo_id: int) -> McpSdkServerConfig:
    """Build the in-process SDK MCP server exposing `search_code`.

    Task 6 passes the result as `mcp_servers={"search": server}` to
    `ClaudeAgentOptions`, and references the tool by its SDK-qualified name
    `mcp__search__search_code`.
    """
    patch_mcp_server()
    return create_sdk_mcp_server(
        name="search", version="1.0.0", tools=[_build_search_tool(conn, repo_id)]
    )
```

- [ ] **Step 10: Update `tests/api/test_ask_route.py` for the shared-connection dependency**

The route no longer calls `get_connection`/`init_schema` itself, so the existing tests'
`patch("coderag_mcp.api.ask_route.get_settings")` no longer does anything useful.
Replace it with a FastAPI dependency override, which also gives each test its own
isolated connection (avoiding cross-test pollution through the module-level `app`).
Rewrite `tests/api/test_ask_route.py`:

```python
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.main import app
from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError
from coderag_mcp.store.db import get_connection, init_schema


@pytest.fixture()
def client(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)
    app.dependency_overrides[get_db_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        del app.dependency_overrides[get_db_conn]
        conn.close()


def test_ask_returns_answer_on_success(client):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", return_value="the answer"),
    ):
        response = client.post(
            "/ask",
            json={"repo_url": "https://github.com/a/b", "question": "what does this do?"},
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "the answer"}


def test_ask_maps_indexing_error_to_400(client):
    with patch(
        "coderag_mcp.api.ask_route.index_and_store_repo",
        side_effect=InvalidRepoURLError("bad host"),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://evil.example/a/b", "question": "?"}
        )

    assert response.status_code == 400
    assert "bad host" in response.json()["detail"]


def test_ask_maps_non_indexing_failure_during_indexing_to_502(client):
    with patch(
        "coderag_mcp.api.ask_route.index_and_store_repo",
        side_effect=RuntimeError("voyage api key invalid"),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not index the repository."


def test_ask_maps_indexing_error_from_run_ask_to_400(client):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch(
            "coderag_mcp.api.ask_route.run_ask",
            side_effect=CloneTimeoutError("clone took too long"),
        ),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 400
    assert "clone took too long" in response.json()["detail"]


def test_ask_maps_orchestrator_failure_to_502(client):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", side_effect=RuntimeError("sdk exploded")),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 502
```

`run_ask`/`index_and_store_repo` are patched as plain `MagicMock`s (via `patch(...,
return_value=...)`/`side_effect=...`) same as before — `unittest.mock.patch`
auto-detects that `run_ask`'s real target (`coderag_mcp.orchestrator.ask.ask`) is an
`async def` and produces an `AsyncMock` automatically, and `run_db_sync(index_and_store_repo,
...)` calling a synchronous `MagicMock` through `asyncio.to_thread` works transparently
too (confirmed by this project's existing test suite passing this exact way already).

- [ ] **Step 11: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (59/59)

- [ ] **Step 12: Commit**

```bash
git add coderag_mcp/store/db.py coderag_mcp/api/deps.py coderag_mcp/api/main.py \
  coderag_mcp/api/ask_route.py coderag_mcp/orchestrator/ask.py coderag_mcp/orchestrator/tools.py \
  tests/api/test_ask_route.py tests/store/test_db.py
git commit -m "perf: shared SQLite connection + asyncio.to_thread offload for /ask"
```

---

### Task 5: API key auth for `/ask` and `/mcp`

**Files:**
- Create: `coderag_mcp/api/auth.py`
- Modify: `coderag_mcp/config.py`
- Modify: `coderag_mcp/api/ask_route.py`
- Modify: `coderag_mcp/api/main.py`
- Test: `tests/api/test_auth.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `get_db_conn` (Task 4, `api/deps.py`) — composed on the same route.
- Produces: `validate_api_key(provided: str | None) -> bool`, `require_api_key(...)` (a
  FastAPI dependency), `ApiKeyMiddleware` (a Starlette `BaseHTTPMiddleware` subclass),
  all in `coderag_mcp/api/auth.py`. No later task in this plan consumes these directly
  (Tasks 6-7 don't touch auth), but any future endpoint should reuse
  `require_api_key`/`ApiKeyMiddleware` rather than re-implementing key checking.

- [ ] **Step 1: Add the settings field**

Edit `coderag_mcp/config.py`, adding one field to `Settings` (after `sqlite_db_path`):

```python
    coderag_api_key: str = ""
```

- [ ] **Step 2: Write the failing test for `validate_api_key`**

Create `tests/api/test_auth.py`:

```python
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.auth import validate_api_key
from coderag_mcp.config import Settings


def _settings(key: str) -> Settings:
    return Settings(coderag_api_key=key)


def test_validate_api_key_allows_anything_when_unset():
    with patch("coderag_mcp.api.auth.get_settings", return_value=_settings("")):
        assert validate_api_key(None) is True
        assert validate_api_key("anything") is True


def test_validate_api_key_requires_exact_match_when_set():
    with patch("coderag_mcp.api.auth.get_settings", return_value=_settings("secret123")):
        assert validate_api_key("secret123") is True
        assert validate_api_key("wrong") is False
        assert validate_api_key(None) is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/api/test_auth.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'coderag_mcp.api.auth'`)

- [ ] **Step 4: Write `coderag_mcp/api/auth.py`**

```python
"""API key auth: one validation core, two adapters (FastAPI Depends + ASGI middleware)
for the two transports (/ask is a normal FastAPI route; /mcp is a mounted Starlette
sub-app, where Depends() never runs)."""
from __future__ import annotations

from fastapi import Header, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from coderag_mcp.config import get_settings


def validate_api_key(provided: str | None) -> bool:
    """True if auth is disabled (empty CODERAG_API_KEY, the default) or provided
    matches the configured key exactly."""
    settings = get_settings()
    if not settings.coderag_api_key:
        return True
    return provided == settings.coderag_api_key


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency for normal routes (e.g. /ask)."""
    if not validate_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for mounted sub-apps (e.g. /mcp), where FastAPI's Depends()
    doesn't run."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not validate_api_key(request.headers.get("x-api-key")):
            return JSONResponse(
                {"detail": "Invalid or missing API key"}, status_code=401
            )
        return await call_next(request)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/api/test_auth.py -v`
Expected: PASS

- [ ] **Step 6: Apply `require_api_key` to `/ask`**

Edit `coderag_mcp/api/ask_route.py`'s imports and route signature:

```python
from coderag_mcp.api.auth import require_api_key
```

```python
@router.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
async def ask_endpoint(
    request: AskRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> AskResponse:
```

- [ ] **Step 7: Apply `ApiKeyMiddleware` to the `/mcp` mount**

Edit `coderag_mcp/api/main.py`, adding the middleware right after building `mcp_app`,
before it's mounted:

```python
from coderag_mcp.api.auth import ApiKeyMiddleware
```

```python
mcp_app = mcp.streamable_http_app(streamable_http_path="/", host=settings.public_host)
mcp_app.add_middleware(ApiKeyMiddleware)
```

- [ ] **Step 8: Write end-to-end auth tests against real HTTP requests**

Add to `tests/api/test_auth.py` (reusing the `client` fixture pattern from Task 4's
`tests/api/test_ask_route.py` — check that file for the exact fixture and copy its
shape here so this file is self-contained):

```python
from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.main import app
from coderag_mcp.store.db import get_connection, init_schema


@pytest.fixture()
def client_with_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "coderag_mcp.api.auth.get_settings", lambda: Settings(coderag_api_key="secret123")
    )
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)
    app.dependency_overrides[get_db_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        del app.dependency_overrides[get_db_conn]
        conn.close()


def test_ask_rejects_missing_key(client_with_key):
    response = client_with_key.post(
        "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
    )
    assert response.status_code == 401


def test_ask_rejects_wrong_key(client_with_key):
    response = client_with_key.post(
        "/ask",
        json={"repo_url": "https://github.com/a/b", "question": "?"},
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401


def test_ask_accepts_correct_key(client_with_key):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", return_value="the answer"),
    ):
        response = client_with_key.post(
            "/ask",
            json={"repo_url": "https://github.com/a/b", "question": "?"},
            headers={"X-API-Key": "secret123"},
        )
    assert response.status_code == 200
```

- [ ] **Step 9: Verify `/mcp`'s auth against a real running server**

Edit `tests/test_mcp_server.py`, adding a new test that starts its own server with a key
configured (the existing `live_server` fixture doesn't set one, so the existing
`test_ping_tool_over_streamable_http` continues to exercise the unauthenticated/dev-mode
path unchanged):

```python
def test_ping_tool_rejected_without_api_key(monkeypatch):
    from coderag_mcp.config import Settings

    monkeypatch.setattr(
        "coderag_mcp.api.auth.get_settings", lambda: Settings(coderag_api_key="secret123")
    )

    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT + 1, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn server did not start in time"

    try:
        import httpx

        response = httpx.post(
            f"http://127.0.0.1:{TEST_PORT + 1}/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 401
    finally:
        server.should_exit = True
        thread.join(timeout=5)
```

This uses a different port (`TEST_PORT + 1`) than the existing `live_server` fixture to
avoid colliding if tests run in the same session. `httpx` (version 0.28.1, confirmed via
`pip show httpx` while writing this plan) is already installed as a transitive
dependency, so the plain `import httpx` above will work without adding it to
`pyproject.toml`.

- [ ] **Step 10: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add coderag_mcp/api/auth.py coderag_mcp/config.py coderag_mcp/api/ask_route.py \
  coderag_mcp/api/main.py tests/api/test_auth.py tests/test_mcp_server.py
git commit -m "feat: add API key auth for /ask and /mcp"
```

---

### Task 6: Collapse the dual-path orchestrator into a single agent

**Files:**
- Modify: `coderag_mcp/orchestrator/agents.py`
- Modify: `coderag_mcp/orchestrator/ask.py`
- Modify: `tests/orchestrator/test_agents.py`
- Modify: `tests/orchestrator/test_ask.py`

**Interfaces:**
- Produces: `ORCHESTRATOR_SYSTEM_PROMPT: str` (in `coderag_mcp/orchestrator/agents.py`).
  `ask(conn, repo_id, repo_url, question) -> str` — signature unchanged, internals
  simplified (`coderag_mcp/orchestrator/ask.py`). Task 7 imports `ask` from
  `coderag_mcp.orchestrator.ask` exactly as Task 4 already established.

**Why this task exists:** external review (relayed by the project owner) flagged that
the dual-path orchestrator (a top-level agent dispatching via the `Agent` tool to
`rag-search`/`code-explorer` subagents) adds token/latency cost from the dispatch
round-trip on every question, when the model itself is capable of choosing between
semantic search and exact file reading if simply given both tools directly. This
replaces subagent routing with direct tool access + one system prompt telling the model
how to choose.

- [ ] **Step 1: Replace `RAG_SEARCH`/`CODE_EXPLORER` with `ORCHESTRATOR_SYSTEM_PROMPT`**

`fresh_clone` is unused after Task 4 (`ask.py` now calls `clone.clone_repo`/
`clone.cleanup_clone` directly via `asyncio.to_thread` — see Task 4 Step 8) and nothing
else in this codebase imports it. Remove it along with the two `AgentDefinition`s.
Replace `coderag_mcp/orchestrator/agents.py` entirely:

```python
"""The single-agent orchestrator's system prompt.

Previously this module also defined two AgentDefinitions (rag-search, code-explorer)
that a top-level orchestrator dispatched to via the Agent tool, plus a fresh_clone
context manager used only by that dispatch flow. That added a subagent-dispatch
round-trip (token + latency cost) on every question for a decision the model itself
can make directly, given both tool families up front - see
docs/superpowers/specs/2026-08-10-single-agent-mcp-tools-auth-design.md's "Bloque 2"
for the full rationale. orchestrator/ask.py now gives the single top-level agent
mcp__search__search_code plus Read/Grep/Glob directly, guided by this prompt, and
clones the repo itself (Task 4's asyncio.to_thread-offloaded clone.clone_repo call).
"""
from __future__ import annotations

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are a code question-answering assistant with two ways to find information "
    "in this repository:\n"
    "- search_code: semantic search over pre-indexed code chunks. Use this for "
    "conceptual questions ('how does X work', 'where is X handled') where matching "
    "the meaning of the question matters more than exact wording.\n"
    "- Read, Grep, Glob: exact search and file reading over the real, current "
    "repository files. Use this for structural or exact-location questions where "
    "precise, up-to-date file:line accuracy matters more than semantic similarity.\n"
    "Choose per question - don't default to only one. Always cite file:line for "
    "anything you reference."
)
```

- [ ] **Step 2: Point `ask.py` at the single agent instead of the two subagents**

Edit `coderag_mcp/orchestrator/ask.py`. Only the imports and the `ClaudeAgentOptions`
construction change — Task 4's clone-offload code (`asyncio.to_thread(clone.clone_repo,
...)` / `asyncio.to_thread(clone.cleanup_clone, repo_dir)`) and the answer-extraction
loop stay exactly as Task 4 left them:

```python
"""Runs the single-agent orchestrator behind ask()."""
from __future__ import annotations

import asyncio
import sqlite3

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from coderag_mcp.indexing import clone
from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT
from coderag_mcp.orchestrator.tools import build_search_server


async def ask(conn: sqlite3.Connection, repo_id: int, repo_url: str, question: str) -> str:
    search_server = build_search_server(conn, repo_id)

    repo_dir = await asyncio.to_thread(clone.clone_repo, repo_url, allow_local_paths=False)
    try:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            allowed_tools=["mcp__search__search_code", "Read", "Grep", "Glob"],
            mcp_servers={"search": search_server},
        )

        answer_parts: list[str] = []
        async for message in query(prompt=question, options=options):
            if not isinstance(message, AssistantMessage):
                continue
            for block in message.content:
                if isinstance(block, TextBlock):
                    answer_parts.append(block.text)

        return "".join(answer_parts)
    finally:
        await asyncio.to_thread(clone.cleanup_clone, repo_dir)
```

- [ ] **Step 3: Rewrite `tests/orchestrator/test_agents.py`**

`fresh_clone` is gone, so its test is gone with it — replace the whole file with a
single test for the new system prompt:

```python
from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT


def test_system_prompt_mentions_both_tool_families():
    assert "search_code" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Read" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Grep" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Glob" in ORCHESTRATOR_SYSTEM_PROMPT
```

- [ ] **Step 4: Rewrite `tests/orchestrator/test_ask.py`**

The mock target changes from `coderag_mcp.orchestrator.ask.fresh_clone` (gone) to the
two functions `ask.py` now calls directly, `coderag_mcp.orchestrator.ask.clone.clone_repo`
and `coderag_mcp.orchestrator.ask.clone.cleanup_clone`. Verified: `ClaudeAgentOptions()`'s
default `agents` value is `None` (checked via `./.venv/bin/python -c "from
claude_agent_sdk import ClaudeAgentOptions; print(ClaudeAgentOptions().agents)"` while
writing this plan), so asserting `options.agents is None` is safe, not speculative.
Replace `tests/orchestrator/test_ask.py` entirely:

```python
from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock

from coderag_mcp.orchestrator.ask import ask


async def _fake_query_stream(*, prompt, options):
    assert prompt == "how does auth work?"
    assert options.allowed_tools == ["mcp__search__search_code", "Read", "Grep", "Glob"]
    assert options.agents is None
    # A non-AssistantMessage should be ignored, not concatenated into the answer.
    yield SystemMessage(subtype="subagent_start", data={})
    yield AssistantMessage(content=[TextBlock(text="Auth is handled in ")], model="test")
    yield AssistantMessage(content=[TextBlock(text="auth.py:10-20.")], model="test")


@pytest.mark.asyncio
async def test_ask_concatenates_streamed_text_and_scopes_cwd(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path) as mock_clone,
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone") as mock_cleanup,
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_fake_query_stream),
    ):
        answer = await ask(conn, repo_id=1, repo_url="https://github.com/a/b", question="how does auth work?")

    assert answer == "Auth is handled in auth.py:10-20."
    mock_clone.assert_called_once_with("https://github.com/a/b", allow_local_paths=False)
    mock_cleanup.assert_called_once_with(tmp_path)
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py tests/orchestrator/test_agents.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add coderag_mcp/orchestrator/agents.py coderag_mcp/orchestrator/ask.py \
  tests/orchestrator/test_agents.py tests/orchestrator/test_ask.py
git commit -m "refactor: collapse dual-path orchestrator into a single agent with direct tool access"
```

---

### Task 7: Real MCP tools (`index_repo`, `search_code`, `ask_repo`)

**Files:**
- Modify: `coderag_mcp/mcp_server/server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `index_and_store_repo` (existing, `orchestrator/indexing_service.py`),
  `ask` (Task 6, `orchestrator/ask.py`), `search_chunks` (existing, `store/chunks.py`),
  `embed_batch` (existing, `embeddings/voyage.py`), `run_db_sync`/`db_lock` (Task 4,
  `store/db.py` — reused here for the *tool-handler-side* offload pattern, but this
  task's shared connection is its own, opened via `MCPServer`'s `lifespan=`, not Task
  4's `app.state.db_conn`; see Global Constraints).
- Produces: three real MCP tools replacing the `ping` placeholder's role as the only
  real functionality on `mcp` — no later task in this plan consumes these.

**Verified against the installed `mcp==2.0.0` SDK before writing this task** (do not
re-derive from scratch - trust this, but re-verify if your installed version differs
from what earlier tasks/CLAUDE.md describe): `MCPServer.__init__` accepts a `lifespan:
Callable[[MCPServer], AbstractAsyncContextManager]` parameter; the value it yields is
reachable inside any `@mcp.tool()`-decorated function via a parameter type-annotated
`Context` (any name), through `ctx.request_context.lifespan_context`. This was
confirmed with a standalone script exercising a real `MCPServer` instance, a real
`streamable_http_app()`, and the exact `async with app.router.lifespan_context(app):`
wrapping `api/main.py` already uses — the custom lifespan's startup/shutdown events
fired correctly through that existing wrapping with zero changes needed to
`api/main.py`.

- [ ] **Step 1: Write the failing end-to-end test for `index_repo`**

Add to `tests/test_mcp_server.py`, after the existing `test_ping_tool_over_streamable_http`:

```python
async def test_index_repo_and_search_code_over_streamable_http(live_server, tmp_path, monkeypatch):
    import subprocess

    from coderag_mcp.config import Settings

    monkeypatch.setattr(
        "coderag_mcp.mcp_server.server.get_settings",
        lambda: Settings(sqlite_db_path=str(tmp_path / "mcp_test.db")),
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "a.py").write_text("def add(a, b):\n    return a + b\n")
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "T"],
        ["git", "add", "."],
        ["git", "commit", "-m", "x"],
    ):
        subprocess.run(cmd, cwd=source_repo, check=True, capture_output=True)

    async with streamable_http_client(live_server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            with patch(
                "coderag_mcp.mcp_server.server.index_and_store_repo"
            ) as mock_index:
                mock_index.return_value = 1
                result = await session.call_tool(
                    "index_repo", {"repo_url": str(source_repo)}
                )
                assert "1" in result.content[0].text
```

Add `from unittest.mock import patch` to the file's imports.

**This test as written won't pass yet and that's expected** — it exercises the tool
through the real MCP transport, which is the point, but `index_repo` doesn't exist. Note
it patches `index_and_store_repo` rather than driving a real clone+embed (that full path
is already covered by this project's live end-to-end verification the project owner ran
manually; this test's job is proving the *transport and lifespan-context wiring* work,
not re-proving indexing itself).

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_mcp_server.py -v`
Expected: FAIL (`index_repo` tool not found / `session.call_tool` errors)

- [ ] **Step 3: Write the three tools with a lifespan-managed shared connection**

Replace `coderag_mcp/mcp_server/server.py` entirely:

```python
"""MCP server exposing CodeRAG-MCP's tools: ping (health check), index_repo,
search_code, ask_repo.

Note: the installed `mcp` SDK (2.0.0) no longer ships
`mcp.server.fastmcp.FastMCP` — that class was renamed/moved to
`mcp.server.mcpserver.MCPServer` in this major version. The public API
(``@mcp.tool()`` decorator, ``mcp.streamable_http_app()``) is otherwise
equivalent for our purposes.

Each tool gets its own shared, lazily-opened-once SQLite connection via this
MCPServer's own `lifespan=` parameter (confirmed against the installed SDK to
correctly fire through api/main.py's existing `async with
mcp_app.router.lifespan_context(mcp_app):` wrapping - no changes needed there).
This mirrors api/ask_route.py's app.state-based shared connection (see
coderag_mcp/api/deps.py) but is a *separate* connection object - the two transports
don't share one Python connection, they each avoid the same "reopen + reload
sqlite-vec per call" cost independently. Tools reach it via a `ctx: Context`
parameter and `ctx.request_context.lifespan_context.conn`.
"""
from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpserver import Context, MCPServer

from coderag_mcp.config import get_settings
from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.orchestrator.ask import ask as run_ask
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.store.chunks import search_chunks
from coderag_mcp.store.db import get_connection, init_schema, run_db_sync


@dataclass
class AppContext:
    conn: sqlite3.Connection


@asynccontextmanager
async def _lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    settings = get_settings()
    conn = get_connection(settings.sqlite_db_path)
    init_schema(conn)
    try:
        yield AppContext(conn=conn)
    finally:
        conn.close()


mcp = MCPServer("coderag-mcp", lifespan=_lifespan)


@mcp.tool()
def ping() -> str:
    """Trivial health-check tool: returns "pong"."""
    return "pong"


@mcp.tool()
async def index_repo(repo_url: str, ctx: Context) -> str:
    """Index a public GitHub/GitLab repo (clone, chunk, embed, store) if not already
    indexed. Returns its repo_id, reusable across search_code/ask_repo calls - though
    both of those also accept repo_url directly and index-on-first-use themselves."""
    conn = ctx.request_context.lifespan_context.conn
    repo_id = await run_db_sync(index_and_store_repo, conn, repo_url)
    return f"Indexed. repo_id={repo_id}"


@mcp.tool()
async def search_code(repo_url: str, query: str, ctx: Context, top_k: int = 5) -> str:
    """Semantic search over repo_url's indexed code chunks. Indexes repo_url first if
    this is the first call for it."""
    conn = ctx.request_context.lifespan_context.conn
    repo_id = await run_db_sync(index_and_store_repo, conn, repo_url)

    def _search():
        query_embedding = embed_batch([query], input_type="query")[0]
        return search_chunks(conn, repo_id, query_embedding, top_k=top_k)

    results = await run_db_sync(_search)
    if not results:
        return "No matches found."
    return "\n\n".join(
        f"{r.file_path}:{r.start_line}-{r.end_line} ({r.symbol_type} {r.symbol_name})\n"
        f"{r.signature}\n{r.source}"
        for r in results
    )


@mcp.tool()
async def ask_repo(repo_url: str, question: str, ctx: Context) -> str:
    """Answer a question about repo_url using the single-agent orchestrator (semantic
    search + exact file reading). Indexes repo_url first if this is the first call for
    it."""
    conn = ctx.request_context.lifespan_context.conn
    repo_id = await run_db_sync(index_and_store_repo, conn, repo_url)
    return await run_ask(conn, repo_id, repo_url, question)
```

`run_ask` here calls straight through to `orchestrator.ask.ask` (imported as `run_ask`
to match this project's existing naming convention from `api/ask_route.py`) — not
wrapped in `run_db_sync`, for the same reason `api/ask_route.py` doesn't wrap it: `ask()`
is already a proper async function (its `query()` call is a non-blocking async
generator; its own blocking clone work already offloads itself internally, per Task 6).

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_mcp_server.py -v`
Expected: PASS. This exact mechanism (an `async def` tool with a `ctx: Context`
parameter, reading `ctx.request_context.lifespan_context` set by `MCPServer`'s
`lifespan=`, called through a real `streamable_http_client`/`ClientSession` over a real
running server) was independently verified end-to-end while writing this plan — not
just read from source, actually run and confirmed to return the lifespan-injected value
correctly. If it fails here, the regression is in this task's specific code, not in an
unverified SDK assumption.

- [ ] **Step 5: Write a real end-to-end test for `ask_repo` and `search_code` too**

Add to `tests/test_mcp_server.py`, reusing the `source_repo` fixture setup pattern from
Step 1 (extract the repeated git-init block into a small local helper function in this
test file if it's now used three times, to avoid copy-pasting it again):

```python
async def test_search_code_and_ask_repo_over_streamable_http(live_server, tmp_path, monkeypatch):
    from coderag_mcp.config import Settings

    monkeypatch.setattr(
        "coderag_mcp.mcp_server.server.get_settings",
        lambda: Settings(sqlite_db_path=str(tmp_path / "mcp_test2.db")),
    )

    async with streamable_http_client(live_server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            with (
                patch(
                    "coderag_mcp.mcp_server.server.index_and_store_repo", return_value=1
                ),
                patch(
                    "coderag_mcp.mcp_server.server.embed_batch",
                    return_value=[[1.0, 0.0, 0.0, 0.0]],
                ),
                patch(
                    "coderag_mcp.mcp_server.server.search_chunks", return_value=[]
                ),
            ):
                result = await session.call_tool(
                    "search_code", {"repo_url": str(tmp_path), "query": "how does auth work"}
                )
                assert result.content[0].text == "No matches found."

            with (
                patch(
                    "coderag_mcp.mcp_server.server.index_and_store_repo", return_value=1
                ),
                patch(
                    "coderag_mcp.mcp_server.server.run_ask", return_value="the answer"
                ),
            ):
                result = await session.call_tool(
                    "ask_repo", {"repo_url": str(tmp_path), "question": "what does this do?"}
                )
                assert result.content[0].text == "the answer"
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS — this is the plan's final task; confirm the whole suite is green before
moving to `superpowers:finishing-a-development-branch` per this repo's standing rule.

- [ ] **Step 8: Commit**

```bash
git add coderag_mcp/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: wire real index_repo/search_code/ask_repo MCP tools"
```

---

## Final check

After Task 7, run `./.venv/bin/pytest -v` once more from the repo root and confirm the
full suite passes before moving to `superpowers:finishing-a-development-branch`. Also
manually sanity-check (not a test — a note for whoever runs the final review) that
`CLAUDE.md` needs updating after this plan lands: the "Known deferred items" entries for
blocking I/O, connection pooling, Voyage client reuse, and duplicated transaction logic
are all resolved by this plan and should move out of that section; the dual-path
orchestrator description throughout `CLAUDE.md` needs updating to describe the
single-agent version; and a new "Auth" note should be added describing
`CODERAG_API_KEY`'s dev-mode-when-empty behavior.
