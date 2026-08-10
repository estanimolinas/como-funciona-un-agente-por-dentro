# Dual-Path Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the SQLite+sqlite-vec persistence layer, Voyage embeddings, and the
Claude Agent SDK orchestrator (RAG subagent + exploration subagent) behind a single
`POST /ask` endpoint, per
`docs/superpowers/specs/2026-08-09-orchestrator-rag-architecture-design.md`.

**Architecture:** `POST /ask` indexes a repo on first request (Plan 2's `index_repo()` +
Voyage embeddings, stored in SQLite/sqlite-vec), then runs a Claude Agent SDK
orchestrator that routes the question to a `rag-search` subagent (semantic search via a
custom `search_code` tool) and/or a `code-explorer` subagent (Read/Grep/Glob over a
fresh on-demand clone), and returns the synthesized answer.

**Tech Stack:** FastAPI, `sqlite3` (stdlib) + `sqlite-vec`, `voyageai`, `claude-agent-sdk`.

**Scope note:** this plan is backend-only. The gitingest-style frontend named in the
spec's scope is deliberately a separate plan — same convention CLAUDE.md already
established for the original frontend step, and the frontend has no dependency on how
the backend's internal modules are split, only on the `POST /ask` contract this plan
delivers.

## Global Constraints

- SQLite + `sqlite-vec` only — no SQLAlchemy/Alembic for this layer (see spec's
  `store/` rationale). Plain `sqlite3` + typed Python functions.
- Cosine similarity is the distance metric (`distance_metric=cosine` on the `vec0`
  virtual table), consistent with `voyage-code-3`'s intended usage.
- `code-explorer` subagent tools are exactly `Read`, `Grep`, `Glob` — never `Bash`,
  `Write`, or `Edit`.
- Every call into `coderag_mcp.indexing.clone`/`pipeline` passes
  `allow_local_paths=False` from production code paths; tests are the only caller of
  `allow_local_paths=True`.
- No automatic re-indexing: `index_and_store_repo()` is idempotent by URL — if a
  `repos` row exists, reuse it, never re-clone/re-embed.
- Subagents are defined programmatically via `AgentDefinition` (not `.claude/agents/*.md`
  files) per the spec.
- The `claude-agent-sdk` package's actual installed API may not match training-data
  assumptions about it (same class of risk as the `mcp` SDK gotcha already documented
  in this repo's `CLAUDE.md`). Before writing code against it, run
  `python -c "import claude_agent_sdk; help(claude_agent_sdk)"` (or read the installed
  package's source under site-packages) and confirm `AgentDefinition`, `ClaudeAgentOptions`,
  `query`, `tool`, and `create_sdk_mcp_server` have the signatures this plan assumes. If
  they differ, adapt the task's code to match the installed version and note the
  discrepancy in your task report.

---

### Task 1: SQLite store — schema, repos, chunks, vector search

**Files:**
- Create: `coderag_mcp/store/__init__.py` (empty)
- Create: `coderag_mcp/store/db.py`
- Create: `coderag_mcp/store/repos.py`
- Create: `coderag_mcp/store/chunks.py`
- Test: `tests/store/__init__.py` (empty)
- Test: `tests/store/test_db.py`
- Test: `tests/store/test_repos.py`
- Test: `tests/store/test_chunks.py`
- Modify: `pyproject.toml` (add `sqlite-vec>=0.1.6` to `dependencies`)

**Interfaces:**
- Produces: `get_connection(db_path: str) -> sqlite3.Connection`,
  `init_schema(conn: sqlite3.Connection, dim: int = EMBEDDING_DIM) -> None`,
  `EMBEDDING_DIM: int = 1024` (all in `store/db.py`).
- Produces: `get_repo_id_by_url(conn, url: str) -> int | None`,
  `create_repo(conn, url: str) -> int` (in `store/repos.py`).
- Produces: `ChunkResult` dataclass (`file_path, symbol_type, symbol_name, start_line,
  end_line, signature, source, distance`), `insert_chunks(conn, repo_id: int, chunks:
  list[Chunk], embeddings: list[list[float]]) -> None`, `search_chunks(conn, repo_id:
  int, query_embedding: list[float], top_k: int = 5) -> list[ChunkResult]` (in
  `store/chunks.py`). Consumes `coderag_mcp.indexing.models.Chunk` from Plan 2.

- [ ] **Step 1: Add the `sqlite-vec` dependency**

Edit `pyproject.toml`'s `dependencies` list to add `"sqlite-vec>=0.1.6",` after the
`tree-sitter-python` line. Run `./.venv/bin/pip install -e .` to install it.

- [ ] **Step 2: Write `coderag_mcp/store/db.py`**

```python
"""SQLite connection and schema management, with the sqlite-vec extension loaded."""
from __future__ import annotations

import sqlite3

import sqlite_vec

EMBEDDING_DIM = 1024  # voyage-code-3 output dimension

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repos(id),
    file_path TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL,
    source TEXT NOT NULL,
    parent_class TEXT
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection, dim: int = EMBEDDING_DIM) -> None:
    conn.executescript(_SCHEMA)
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            repo_id INTEGER PARTITION KEY,
            embedding FLOAT[{dim}] distance_metric=cosine
        )
        """
    )
    conn.commit()
```

- [ ] **Step 3: Write the failing test for `db.py`**

`tests/store/test_db.py`:

```python
import sqlite3

from coderag_mcp.store.db import get_connection, init_schema


def test_init_schema_creates_tables(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
        )
    }
    assert {"repos", "chunks", "chunk_vectors"} <= tables


def test_init_schema_is_idempotent(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    init_schema(conn, dim=4)  # must not raise
```

- [ ] **Step 4: Run it, confirm it fails, then it's already implemented — run again to confirm pass**

Run: `./.venv/bin/pytest tests/store/test_db.py -v`
Expected: PASS (db.py was written in Step 2). If `sqlite_vec.load` raises
`AttributeError` or similar, re-read the installed package's actual API per the Global
Constraints note and adjust `get_connection`.

- [ ] **Step 5: Write `coderag_mcp/store/repos.py`**

```python
"""Repo row lookups/creation, keyed by URL."""
from __future__ import annotations

import sqlite3


def get_repo_id_by_url(conn: sqlite3.Connection, url: str) -> int | None:
    row = conn.execute("SELECT id FROM repos WHERE url = ?", (url,)).fetchone()
    return row[0] if row else None


def create_repo(conn: sqlite3.Connection, url: str) -> int:
    cursor = conn.execute("INSERT INTO repos (url) VALUES (?)", (url,))
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid
```

- [ ] **Step 6: Write and run the test for `repos.py`**

`tests/store/test_repos.py`:

```python
from coderag_mcp.store.db import get_connection, init_schema
from coderag_mcp.store.repos import create_repo, get_repo_id_by_url


def test_create_and_lookup_repo(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    assert get_repo_id_by_url(conn, "https://github.com/a/b") is None

    repo_id = create_repo(conn, "https://github.com/a/b")
    assert get_repo_id_by_url(conn, "https://github.com/a/b") == repo_id
```

Run: `./.venv/bin/pytest tests/store/test_repos.py -v`
Expected: PASS

- [ ] **Step 7: Write `coderag_mcp/store/chunks.py`**

```python
"""Chunk storage and cosine-similarity search over sqlite-vec."""
from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass

from coderag_mcp.indexing.models import Chunk


@dataclass
class ChunkResult:
    file_path: str
    symbol_type: str
    symbol_name: str
    start_line: int
    end_line: int
    signature: str
    source: str
    distance: float


def _serialize(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def insert_chunks(
    conn: sqlite3.Connection,
    repo_id: int,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must be the same length")

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
    conn.commit()


def search_chunks(
    conn: sqlite3.Connection,
    repo_id: int,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[ChunkResult]:
    matches = conn.execute(
        """
        SELECT chunk_id, distance
        FROM chunk_vectors
        WHERE embedding MATCH ? AND k = ? AND repo_id = ?
        ORDER BY distance
        """,
        (_serialize(query_embedding), top_k, repo_id),
    ).fetchall()
    if not matches:
        return []

    distance_by_id = {chunk_id: distance for chunk_id, distance in matches}
    placeholders = ",".join("?" * len(distance_by_id))
    rows = conn.execute(
        f"""
        SELECT id, file_path, symbol_type, symbol_name, start_line, end_line,
               signature, source
        FROM chunks WHERE id IN ({placeholders})
        """,
        list(distance_by_id.keys()),
    ).fetchall()

    results = [
        ChunkResult(*row[1:], distance=distance_by_id[row[0]]) for row in rows
    ]
    results.sort(key=lambda r: r.distance)
    return results
```

- [ ] **Step 8: Write and run the test for `chunks.py`**

`tests/store/test_chunks.py`:

```python
from coderag_mcp.indexing.models import Chunk
from coderag_mcp.store.chunks import insert_chunks, search_chunks
from coderag_mcp.store.db import get_connection, init_schema
from coderag_mcp.store.repos import create_repo


def _chunk(name: str) -> Chunk:
    return Chunk(
        repo_url="https://github.com/a/b",
        file_path="mod.py",
        symbol_type="function",
        symbol_name=name,
        start_line=1,
        end_line=2,
        signature=f"def {name}():",
        source=f"def {name}():\n    pass",
    )


def test_search_chunks_ranks_by_similarity(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    repo_id = create_repo(conn, "https://github.com/a/b")

    chunks = [_chunk("near"), _chunk("far")]
    embeddings = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    insert_chunks(conn, repo_id, chunks, embeddings)

    results = search_chunks(conn, repo_id, [1.0, 0.0, 0.0, 0.0], top_k=2)

    assert [r.symbol_name for r in results] == ["near", "far"]


def test_search_chunks_scoped_to_repo(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    repo_a = create_repo(conn, "https://github.com/a/a")
    repo_b = create_repo(conn, "https://github.com/b/b")

    insert_chunks(conn, repo_a, [_chunk("only_in_a")], [[1.0, 0.0, 0.0, 0.0]])
    insert_chunks(conn, repo_b, [_chunk("only_in_b")], [[1.0, 0.0, 0.0, 0.0]])

    results = search_chunks(conn, repo_a, [1.0, 0.0, 0.0, 0.0], top_k=5)

    assert [r.symbol_name for r in results] == ["only_in_a"]
```

Run: `./.venv/bin/pytest tests/store/ -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Commit**

```bash
git add coderag_mcp/store tests/store pyproject.toml
git commit -m "feat: add SQLite + sqlite-vec persistence layer"
```

---

### Task 2: Voyage embeddings client

**Files:**
- Create: `coderag_mcp/embeddings/__init__.py` (empty)
- Create: `coderag_mcp/embeddings/voyage.py`
- Test: `tests/embeddings/__init__.py` (empty)
- Test: `tests/embeddings/test_voyage.py`
- Modify: `coderag_mcp/config.py` (add `voyage_api_key: str = ""`)
- Modify: `pyproject.toml` (add `voyageai>=0.3.0` to `dependencies`)

**Interfaces:**
- Consumes: `coderag_mcp.config.get_settings()` for `voyage_api_key`.
- Produces: `embed_batch(texts: list[str]) -> list[list[float]]` in
  `coderag_mcp/embeddings/voyage.py`. Task 3 calls this directly.

- [ ] **Step 1: Add the dependency and config field**

Edit `pyproject.toml`'s `dependencies` to add `"voyageai>=0.3.0",`.
Edit `coderag_mcp/config.py`, adding `voyage_api_key: str = ""` as a new field on
`Settings`, alongside `public_host`.
Run: `./.venv/bin/pip install -e .`

- [ ] **Step 2: Write `coderag_mcp/embeddings/voyage.py`**

```python
"""Voyage AI embedding client for code chunks."""
from __future__ import annotations

import voyageai

from coderag_mcp.config import get_settings

MODEL = "voyage-code-3"


def embed_batch(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    client = voyageai.Client(api_key=settings.voyage_api_key)
    result = client.embed(texts, model=MODEL, input_type="document")
    return result.embeddings
```

- [ ] **Step 3: Write the test, mocking the Voyage client**

`tests/embeddings/test_voyage.py`:

```python
from unittest.mock import MagicMock, patch

from coderag_mcp.embeddings.voyage import embed_batch


def test_embed_batch_calls_voyage_with_code3_model():
    fake_result = MagicMock(embeddings=[[0.1, 0.2], [0.3, 0.4]])
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.return_value = fake_result

        result = embed_batch(["def a(): pass", "def b(): pass"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        mock_client_cls.return_value.embed.assert_called_once_with(
            ["def a(): pass", "def b(): pass"],
            model="voyage-code-3",
            input_type="document",
        )
```

- [ ] **Step 4: Run the test**

Run: `./.venv/bin/pytest tests/embeddings/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coderag_mcp/embeddings tests/embeddings coderag_mcp/config.py pyproject.toml
git commit -m "feat: add Voyage voyage-code-3 embedding client"
```

---

### Task 3: Idempotent index-and-store service

**Files:**
- Create: `coderag_mcp/orchestrator/__init__.py` (empty)
- Create: `coderag_mcp/orchestrator/indexing_service.py`
- Test: `tests/orchestrator/__init__.py` (empty)
- Test: `tests/orchestrator/test_indexing_service.py`

**Interfaces:**
- Consumes: `coderag_mcp.indexing.pipeline.index_repo(url, *, allow_local_paths=False)
  -> list[Chunk]` (Plan 2), `coderag_mcp.embeddings.voyage.embed_batch` (Task 2),
  `coderag_mcp.store.repos.{get_repo_id_by_url, create_repo}`,
  `coderag_mcp.store.chunks.insert_chunks` (Task 1).
- Produces: `index_and_store_repo(conn: sqlite3.Connection, repo_url: str) -> int`
  (returns `repo_id`). Task 7 (API layer) calls this directly.

- [ ] **Step 1: Write `coderag_mcp/orchestrator/indexing_service.py`**

```python
"""Idempotent glue: index a repo (Plan 2 pipeline) and store its embedded chunks."""
from __future__ import annotations

import sqlite3

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.indexing.pipeline import index_repo
from coderag_mcp.store import chunks as chunk_store
from coderag_mcp.store import repos as repo_store


def index_and_store_repo(conn: sqlite3.Connection, repo_url: str) -> int:
    """Return the repo's id, indexing and embedding it first if not already stored."""
    existing_id = repo_store.get_repo_id_by_url(conn, repo_url)
    if existing_id is not None:
        return existing_id

    extracted = index_repo(repo_url, allow_local_paths=False)
    repo_id = repo_store.create_repo(conn, repo_url)

    if extracted:
        embeddings = embed_batch([chunk.source for chunk in extracted])
        chunk_store.insert_chunks(conn, repo_id, extracted, embeddings)

    return repo_id
```

- [ ] **Step 2: Write the test, mocking `index_repo` and `embed_batch`**

`tests/orchestrator/test_indexing_service.py`:

```python
from unittest.mock import patch

from coderag_mcp.indexing.models import Chunk
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.store.chunks import search_chunks
from coderag_mcp.store.db import get_connection, init_schema


def _chunk() -> Chunk:
    return Chunk(
        repo_url="https://github.com/a/b",
        file_path="mod.py",
        symbol_type="function",
        symbol_name="f",
        start_line=1,
        end_line=2,
        signature="def f():",
        source="def f():\n    pass",
    )


def test_indexes_and_stores_on_first_call(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ) as mock_index,
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
    ):
        repo_id = index_and_store_repo(conn, "https://github.com/a/b")

    mock_index.assert_called_once_with(
        "https://github.com/a/b", allow_local_paths=False
    )
    results = search_chunks(conn, repo_id, [1.0, 0.0, 0.0, 0.0], top_k=1)
    assert results[0].symbol_name == "f"


def test_second_call_reuses_existing_repo_without_reindexing(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ) as mock_index,
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
    ):
        first_id = index_and_store_repo(conn, "https://github.com/a/b")
        second_id = index_and_store_repo(conn, "https://github.com/a/b")

    assert first_id == second_id
    mock_index.assert_called_once()
```

- [ ] **Step 3: Run the tests**

Run: `./.venv/bin/pytest tests/orchestrator/test_indexing_service.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add coderag_mcp/orchestrator tests/orchestrator
git commit -m "feat: add idempotent index-and-store service"
```

---

### Task 4: `search_code` tool and `rag-search` agent definition

**Files:**
- Create: `coderag_mcp/orchestrator/tools.py`
- Test: `tests/orchestrator/test_tools.py`
- Modify: `pyproject.toml` (add `claude-agent-sdk>=0.1.0` to `dependencies`)

**Interfaces:**
- Consumes: `coderag_mcp.store.chunks.search_chunks` (Task 1),
  `coderag_mcp.embeddings.voyage.embed_batch` (Task 2).
- Produces: `build_search_server(conn: sqlite3.Connection, repo_id: int)` returning an
  SDK MCP server object, in `coderag_mcp/orchestrator/tools.py`. Task 6 calls this and
  passes the result as `mcp_servers={"search": server}` to `ClaudeAgentOptions`, and
  references the tool by its SDK-qualified name `mcp__search__search_code`.

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml`'s `dependencies` to add `"claude-agent-sdk>=0.1.0",`. Run
`./.venv/bin/pip install -e .`. Per the Global Constraints note, confirm
`claude_agent_sdk.tool` and `claude_agent_sdk.create_sdk_mcp_server` exist with a
decorator/factory shape matching Step 2 below before proceeding — adjust Step 2 to the
installed version's actual signature if it differs.

- [ ] **Step 2: Write `coderag_mcp/orchestrator/tools.py`**

```python
"""The search_code custom tool, exposed to the rag-search subagent as an in-process
MCP server per the Claude Agent SDK's custom-tool mechanism."""
from __future__ import annotations

import sqlite3

from claude_agent_sdk import create_sdk_mcp_server, tool

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.store.chunks import search_chunks


def build_search_server(conn: sqlite3.Connection, repo_id: int):
    @tool(
        "search_code",
        "Semantic search over the indexed repo's code chunks. Returns the top "
        "matching functions/classes/methods with file path, line range, and source.",
        {"query": str, "top_k": int},
    )
    async def search_code(args: dict) -> dict:
        query_embedding = embed_batch([args["query"]])[0]
        top_k = args.get("top_k", 5)
        results = search_chunks(conn, repo_id, query_embedding, top_k=top_k)

        if not results:
            text = "No matches found."
        else:
            text = "\n\n".join(
                f"{r.file_path}:{r.start_line}-{r.end_line} "
                f"({r.symbol_type} {r.symbol_name})\n{r.signature}\n{r.source}"
                for r in results
            )
        return {"content": [{"type": "text", "text": text}]}

    return create_sdk_mcp_server(name="search", version="1.0.0", tools=[search_code])
```

- [ ] **Step 3: Write the test, calling the tool function directly**

`tests/orchestrator/test_tools.py`:

```python
import asyncio

from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.orchestrator.tools import build_search_server
from coderag_mcp.store.db import get_connection, init_schema
from unittest.mock import patch

from coderag_mcp.indexing.models import Chunk


def _chunk() -> Chunk:
    return Chunk(
        repo_url="https://github.com/a/b",
        file_path="mod.py",
        symbol_type="function",
        symbol_name="f",
        start_line=1,
        end_line=2,
        signature="def f():",
        source="def f():\n    pass",
    )


def test_search_code_tool_returns_matching_chunk(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
    ):
        repo_id = index_and_store_repo(conn, "https://github.com/a/b")

    server = build_search_server(conn, repo_id)
    search_tool = server.tools["search_code"]  # ⚠️ verify attribute name against
                                                 # the installed SDK if this fails

    with patch(
        "coderag_mcp.orchestrator.tools.embed_batch",
        return_value=[[1.0, 0.0, 0.0, 0.0]],
    ):
        result = asyncio.run(search_tool.handler({"query": "f", "top_k": 1}))

    assert "mod.py:1-2" in result["content"][0]["text"]
```

**⚠️ Cannot verify from the plan alone:** the exact attribute path to reach a
registered tool's callable on the object `create_sdk_mcp_server` returns is not
confirmed against the installed `claude-agent-sdk` version. If `server.tools[...]`
or `.handler` don't exist, inspect the installed package (`python -c "import
claude_agent_sdk, inspect; print(inspect.getsource(claude_agent_sdk.create_sdk_mcp_server))"`)
and adjust the test to call the underlying function however that version exposes it.
The important behavior under test — the tool queries `search_chunks` and formats
`file:line` in its output — does not change.

- [ ] **Step 4: Run the test, fixing the SDK-specific access pattern per the note above if needed**

Run: `./.venv/bin/pytest tests/orchestrator/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coderag_mcp/orchestrator/tools.py tests/orchestrator/test_tools.py pyproject.toml
git commit -m "feat: add search_code tool as an SDK MCP server"
```

---

### Task 5: `code-explorer` agent and on-demand clone scoping

**Files:**
- Create: `coderag_mcp/orchestrator/agents.py`
- Test: `tests/orchestrator/test_agents.py`

**Interfaces:**
- Consumes: `coderag_mcp.indexing.clone.{clone_repo, cleanup_clone}` (Plan 2).
- Produces: `RAG_SEARCH: AgentDefinition`, `CODE_EXPLORER: AgentDefinition`,
  `fresh_clone(repo_url: str)` (a context manager yielding a `Path`), all in
  `coderag_mcp/orchestrator/agents.py`. Task 6 imports all three.

- [ ] **Step 1: Write `coderag_mcp/orchestrator/agents.py`**

```python
"""Subagent definitions and the on-demand clone used by code-explorer."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from claude_agent_sdk import AgentDefinition

from coderag_mcp.indexing import clone


@contextmanager
def fresh_clone(repo_url: str) -> Iterator[Path]:
    """Clone repo_url into a fresh temp dir for this request; always cleaned up after."""
    repo_dir = clone.clone_repo(repo_url, allow_local_paths=False)
    try:
        yield repo_dir
    finally:
        clone.cleanup_clone(repo_dir)


RAG_SEARCH = AgentDefinition(
    description=(
        "Answers conceptual questions about the repo using semantic search over "
        "indexed code chunks. Use for 'how does X work' / 'where is X handled' style "
        "questions where similarity to the question's meaning is what matters."
    ),
    prompt=(
        "You are a semantic code search specialist. Use the search_code tool to find "
        "relevant chunks, then explain what they do, citing file:line for each chunk "
        "you reference."
    ),
    tools=["mcp__search__search_code"],
)

CODE_EXPLORER = AgentDefinition(
    description=(
        "Explores the actual cloned repository files with exact search (grep/glob) "
        "and reads real file content. Use for structural or exact-location questions "
        "where current file:line accuracy matters more than semantic similarity."
    ),
    prompt=(
        "You are a code exploration specialist. Use Grep and Glob to locate exact "
        "code, then Read to inspect it. Always report file paths relative to the repo "
        "root and exact line numbers from what you actually read - never guess line "
        "numbers or rely on memory of similar codebases."
    ),
    tools=["Read", "Grep", "Glob"],
)
```

- [ ] **Step 2: Write the test**

`tests/orchestrator/test_agents.py`:

```python
from coderag_mcp.orchestrator.agents import CODE_EXPLORER, RAG_SEARCH, fresh_clone


def test_code_explorer_tools_exclude_bash_and_write():
    assert CODE_EXPLORER.tools == ["Read", "Grep", "Glob"]
    assert "Bash" not in CODE_EXPLORER.tools
    assert "Write" not in CODE_EXPLORER.tools
    assert "Edit" not in CODE_EXPLORER.tools


def test_rag_search_uses_search_code_tool_only():
    assert RAG_SEARCH.tools == ["mcp__search__search_code"]


def test_fresh_clone_yields_and_cleans_up_repo_dir(tmp_path):
    import subprocess

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=source_repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=source_repo, check=True, capture_output=True
    )
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "x"], cwd=source_repo, check=True, capture_output=True
    )

    from coderag_mcp.indexing import clone as clone_module

    # fresh_clone always passes allow_local_paths=False; to test the context-manager
    # contract without network access, monkeypatch clone_repo/cleanup_clone directly.
    calls = []

    def fake_clone_repo(url, *, allow_local_paths=False):
        calls.append(("clone", url, allow_local_paths))
        return source_repo

    def fake_cleanup(path):
        calls.append(("cleanup", path))

    orig_clone, orig_cleanup = clone_module.clone_repo, clone_module.cleanup_clone
    clone_module.clone_repo = fake_clone_repo
    clone_module.cleanup_clone = fake_cleanup
    try:
        with fresh_clone("https://github.com/a/b") as repo_dir:
            assert repo_dir == source_repo
            assert calls == [("clone", "https://github.com/a/b", False)]
        assert calls[-1] == ("cleanup", source_repo)
    finally:
        clone_module.clone_repo = orig_clone
        clone_module.cleanup_clone = orig_cleanup
```

- [ ] **Step 3: Run the tests**

Run: `./.venv/bin/pytest tests/orchestrator/test_agents.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add coderag_mcp/orchestrator/agents.py tests/orchestrator/test_agents.py
git commit -m "feat: add rag-search/code-explorer agent definitions and fresh_clone helper"
```

---

### Task 6: Orchestrator `ask()` entry point

**Files:**
- Create: `coderag_mcp/orchestrator/ask.py`
- Test: `tests/orchestrator/test_ask.py`

**Interfaces:**
- Consumes: `build_search_server` (Task 4), `RAG_SEARCH`, `CODE_EXPLORER`,
  `fresh_clone` (Task 5).
- Produces: `async def ask(conn: sqlite3.Connection, repo_id: int, repo_url: str,
  question: str) -> str` in `coderag_mcp/orchestrator/ask.py`. Task 7 (API layer)
  calls this directly.

**Note on eager cloning:** the spec describes `code-explorer`'s clone as triggered
"if invoked." In practice, `ClaudeAgentOptions.cwd` must be set before the orchestrator
runs so `code-explorer`'s Read/Grep/Glob resolve inside the clone — there's no way to
clone lazily only when that subagent is actually chosen without hooking into the SDK's
internal tool-dispatch, which is out of scope for v1. This task therefore clones
eagerly on every `ask()` call, even when the orchestrator ends up using only
`rag-search`. This is a deliberate, documented v1 simplification (latency cost on every
question, not just explorer questions) — flag it in your task report so the final
review can confirm this tradeoff is acceptable rather than silently diverging from the
spec's wording.

- [ ] **Step 1: Write `coderag_mcp/orchestrator/ask.py`**

```python
"""Ties the two subagents together behind a single ask() call."""
from __future__ import annotations

import sqlite3

from claude_agent_sdk import ClaudeAgentOptions, query

from coderag_mcp.orchestrator.agents import CODE_EXPLORER, RAG_SEARCH, fresh_clone
from coderag_mcp.orchestrator.tools import build_search_server


async def ask(conn: sqlite3.Connection, repo_id: int, repo_url: str, question: str) -> str:
    search_server = build_search_server(conn, repo_id)

    with fresh_clone(repo_url) as repo_dir:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            allowed_tools=["Agent"],
            mcp_servers={"search": search_server},
            agents={"rag-search": RAG_SEARCH, "code-explorer": CODE_EXPLORER},
        )

        answer_parts: list[str] = []
        async for message in query(prompt=question, options=options):
            for block in getattr(message, "content", []):
                text = getattr(block, "text", None)
                if text:
                    answer_parts.append(text)

        return "".join(answer_parts)
```

- [ ] **Step 2: Write the test, mocking `query` and `fresh_clone`**

`tests/orchestrator/test_ask.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coderag_mcp.orchestrator.ask import ask


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


async def _fake_query_stream(*, prompt, options):
    assert prompt == "how does auth work?"
    assert options.agents.keys() == {"rag-search", "code-explorer"}
    assert "Agent" in options.allowed_tools
    yield _FakeMessage("Auth is handled in ")
    yield _FakeMessage("auth.py:10-20.")


@pytest.mark.asyncio
async def test_ask_concatenates_streamed_text_and_scopes_cwd(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.fresh_clone") as mock_fresh_clone,
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_fake_query_stream),
    ):
        mock_fresh_clone.return_value.__enter__.return_value = tmp_path
        mock_fresh_clone.return_value.__exit__.return_value = False

        answer = await ask(conn, repo_id=1, repo_url="https://github.com/a/b", question="how does auth work?")

    assert answer == "Auth is handled in auth.py:10-20."
    mock_fresh_clone.assert_called_once_with("https://github.com/a/b")
```

- [ ] **Step 3: Run the test**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add coderag_mcp/orchestrator/ask.py tests/orchestrator/test_ask.py
git commit -m "feat: add orchestrator ask() entry point"
```

---

### Task 7: `POST /ask` API endpoint

**Files:**
- Create: `coderag_mcp/api/schemas.py`
- Create: `coderag_mcp/api/ask_route.py`
- Modify: `coderag_mcp/api/main.py` (include the new router)
- Modify: `coderag_mcp/config.py` (add `sqlite_db_path: str = "coderag.db"`)
- Test: `tests/api/test_ask_route.py`

**Interfaces:**
- Consumes: `index_and_store_repo` (Task 3), `ask` (Task 6),
  `coderag_mcp.store.db.{get_connection, init_schema}` (Task 1),
  `coderag_mcp.indexing.models.IndexingError` (Plan 2).

- [ ] **Step 1: Add the config field**

Edit `coderag_mcp/config.py`, adding `sqlite_db_path: str = "coderag.db"` to
`Settings`.

- [ ] **Step 2: Write `coderag_mcp/api/schemas.py`**

```python
"""Pydantic request/response models for the /ask endpoint."""
from __future__ import annotations

from pydantic import BaseModel


class AskRequest(BaseModel):
    repo_url: str
    question: str


class AskResponse(BaseModel):
    answer: str
```

- [ ] **Step 3: Write `coderag_mcp/api/ask_route.py`**

```python
"""POST /ask: index-on-first-use, then route the question through the orchestrator."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from coderag_mcp.api.schemas import AskRequest, AskResponse
from coderag_mcp.config import get_settings
from coderag_mcp.indexing.models import IndexingError
from coderag_mcp.orchestrator.ask import ask as run_ask
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.store.db import get_connection, init_schema

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest) -> AskResponse:
    settings = get_settings()
    conn = get_connection(settings.sqlite_db_path)
    init_schema(conn)

    try:
        try:
            repo_id = index_and_store_repo(conn, request.repo_url)
        except IndexingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            answer = await run_ask(conn, repo_id, request.repo_url, request.question)
        except Exception as exc:  # noqa: BLE001 - any orchestrator/subagent failure
            raise HTTPException(
                status_code=502, detail="Could not answer the question."
            ) from exc
    finally:
        conn.close()

    return AskResponse(answer=answer)
```

- [ ] **Step 4: Wire the router into `coderag_mcp/api/main.py`**

Add near the top with the other imports:

```python
from coderag_mcp.api.ask_route import router as ask_router
```

Add after `app.mount("/mcp", mcp_app)`:

```python
app.include_router(ask_router)
```

- [ ] **Step 5: Write the test**

`tests/api/test_ask_route.py` (create `tests/api/__init__.py` empty if it doesn't
exist):

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from coderag_mcp.api.main import app
from coderag_mcp.indexing.models import InvalidRepoURLError


def test_ask_returns_answer_on_success(tmp_path):
    with (
        patch("coderag_mcp.api.ask_route.get_settings") as mock_settings,
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", return_value="the answer"),
    ):
        mock_settings.return_value.sqlite_db_path = str(tmp_path / "test.db")

        client = TestClient(app)
        response = client.post(
            "/ask",
            json={"repo_url": "https://github.com/a/b", "question": "what does this do?"},
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "the answer"}


def test_ask_maps_indexing_error_to_400(tmp_path):
    with (
        patch("coderag_mcp.api.ask_route.get_settings") as mock_settings,
        patch(
            "coderag_mcp.api.ask_route.index_and_store_repo",
            side_effect=InvalidRepoURLError("bad host"),
        ),
    ):
        mock_settings.return_value.sqlite_db_path = str(tmp_path / "test.db")

        client = TestClient(app)
        response = client.post(
            "/ask", json={"repo_url": "https://evil.example/a/b", "question": "?"}
        )

    assert response.status_code == 400
    assert "bad host" in response.json()["detail"]


def test_ask_maps_orchestrator_failure_to_502(tmp_path):
    with (
        patch("coderag_mcp.api.ask_route.get_settings") as mock_settings,
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch(
            "coderag_mcp.api.ask_route.run_ask", side_effect=RuntimeError("sdk exploded")
        ),
    ):
        mock_settings.return_value.sqlite_db_path = str(tmp_path / "test.db")

        client = TestClient(app)
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 502
```

- [ ] **Step 6: Run the full test suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (all tests, including Plan 1/2's existing suite — this task must not
break anything already passing)

- [ ] **Step 7: Commit**

```bash
git add coderag_mcp/api tests/api coderag_mcp/config.py
git commit -m "feat: add POST /ask endpoint tying orchestrator to the API"
```

---

## Final check

After Task 7, run `./.venv/bin/pytest -v` once more from the repo root and confirm the
full suite (Plans 1, 2, and this plan) passes before moving to
`superpowers:finishing-a-development-branch`.
