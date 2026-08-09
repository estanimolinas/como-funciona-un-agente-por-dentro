# Indexing Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `coderag_mcp.indexing.pipeline.index_repo(url) -> list[Chunk]`: clone a public Python repo, parse it with tree-sitter, and produce function/class/method-level chunks with metadata — no HTTP endpoint, no database, no embeddings.

**Architecture:** Four small modules (`models.py`, `clone.py`, `chunker.py`, `pipeline.py`) under `coderag_mcp/indexing/`, each independently testable, composed by `pipeline.index_repo`. Tests run against a local git fixture repo — no network access required.

**Tech Stack:** `tree-sitter` + `tree-sitter-python` (official bindings) for parsing; `subprocess` + system `git` for cloning; stdlib only otherwise.

## Global Constraints

- Python 3.11+, existing venv at `.venv/` — use `./.venv/bin/pip` and `./.venv/bin/pytest` for every install/test command in this plan.
- No new runtime dependencies beyond `tree-sitter` and `tree-sitter-python` (spec: "Dependencies added").
- All limits (`ALLOWED_HOSTS`, `MAX_REPO_SIZE_MB`, `CLONE_TIMEOUT_S`, `PIPELINE_TIMEOUT_S`, `MAX_FILE_COUNT`) are hardcoded module-level constants, not `pydantic-settings` fields (spec: "Constants (hardcoded for this plan)").
- Per-file parse failures must never raise — log a warning and return `[]` for that file (spec: "Error handling").
- Job-level failures (bad host, timeout, size cap, file-count cap) raise typed exceptions, all subclassing `IndexingError` (spec: "Error handling").
- No HTTP endpoint, no MCP tool wiring, no database, no embeddings in this plan — `index_repo` is a pure function (spec: "Scope").
- Tests must not require network access — clone from a local git fixture repo created in a pytest fixture (spec: "Testing").

Reference spec: `docs/superpowers/specs/2026-08-08-indexing-pipeline-design.md`

---

### Task 1: Package skeleton, exceptions, and `Chunk` model

**Files:**
- Create: `coderag_mcp/indexing/__init__.py`
- Create: `coderag_mcp/indexing/models.py`
- Test: `tests/indexing/__init__.py`
- Test: `tests/indexing/test_models.py`

**Interfaces:**
- Produces: `Chunk` dataclass with fields `repo_url: str`, `file_path: str`, `symbol_type: str`, `symbol_name: str`, `start_line: int`, `end_line: int`, `signature: str`, `source: str`, `parent_class: str | None = None`.
- Produces: exception hierarchy — `IndexingError(Exception)` base, and subclasses `InvalidRepoURLError`, `CloneTimeoutError`, `RepoTooLargeError`, `TooManyFilesError`, `PipelineTimeoutError`.

- [ ] **Step 1: Write the failing test**

Create `tests/indexing/__init__.py` (empty file, makes `tests/indexing` a package).

Create `tests/indexing/test_models.py`:

```python
"""Tests for the Chunk dataclass and indexing exception hierarchy."""
from __future__ import annotations

import pytest

from coderag_mcp.indexing.models import (
    Chunk,
    CloneTimeoutError,
    IndexingError,
    InvalidRepoURLError,
    PipelineTimeoutError,
    RepoTooLargeError,
    TooManyFilesError,
)


def test_chunk_holds_expected_fields():
    chunk = Chunk(
        repo_url="https://github.com/example/repo",
        file_path="pkg/mod.py",
        symbol_type="function",
        symbol_name="add",
        start_line=1,
        end_line=3,
        signature="def add(a: int, b: int) -> int:",
        source="def add(a: int, b: int) -> int:\n    return a + b\n",
    )
    assert chunk.parent_class is None
    assert chunk.symbol_type == "function"
    assert chunk.start_line == 1
    assert chunk.end_line == 3


@pytest.mark.parametrize(
    "exc_type",
    [
        InvalidRepoURLError,
        CloneTimeoutError,
        RepoTooLargeError,
        TooManyFilesError,
        PipelineTimeoutError,
    ],
)
def test_job_level_exceptions_subclass_indexing_error(exc_type):
    assert issubclass(exc_type, IndexingError)
    assert issubclass(IndexingError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/indexing/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coderag_mcp.indexing'`

- [ ] **Step 3: Write minimal implementation**

Create `coderag_mcp/indexing/__init__.py` (empty file).

Create `coderag_mcp/indexing/models.py`:

```python
"""Data model and exception hierarchy for the indexing pipeline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    """A single AST-aware unit of code extracted from a repo file."""

    repo_url: str
    file_path: str
    symbol_type: str  # "function" | "class" | "method"
    symbol_name: str
    start_line: int
    end_line: int
    signature: str
    source: str
    parent_class: str | None = None


class IndexingError(Exception):
    """Base class for job-level indexing pipeline failures."""


class InvalidRepoURLError(IndexingError):
    """The repo URL's host is not on the allowlist, or the URL is malformed."""


class CloneTimeoutError(IndexingError):
    """`git clone` did not finish within the allotted time."""


class RepoTooLargeError(IndexingError):
    """The cloned repo's working tree exceeds the size cap."""


class TooManyFilesError(IndexingError):
    """The repo has more `.py` files than the pipeline will parse."""


class PipelineTimeoutError(IndexingError):
    """Clone + parse together exceeded the pipeline's wall-clock budget."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/indexing/test_models.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add coderag_mcp/indexing/__init__.py coderag_mcp/indexing/models.py tests/indexing/__init__.py tests/indexing/test_models.py
git commit -m "feat(indexing): add Chunk model and exception hierarchy"
```

---

### Task 2: Local git fixture repo for indexing tests

**Files:**
- Create: `tests/indexing/conftest.py`
- Test: `tests/indexing/test_fixture_repo.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: pytest fixture `fixture_repo(tmp_path) -> Path` — a real local git repository (via `git init` + a commit) containing three files: `functions.py` (one top-level function), `classes.py` (one class with two methods), `broken.py` (invalid Python syntax). Tasks 3-5 depend on this fixture by name (pytest auto-discovers fixtures from `conftest.py` in the same directory).

- [ ] **Step 1: Write the failing test**

Create `tests/indexing/conftest.py`:

```python
"""Shared fixtures for indexing pipeline tests: a real local git repo."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

FUNCTIONS_PY = '''\
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''

CLASSES_PY = '''\
class Greeter:
    """Greets people by name."""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        """Return a greeting for self.name."""
        return f"Hello, {self.name}"
'''

BROKEN_PY = '''\
def broken(
    this is not valid python syntax
'''


def _run_git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    """Create a real local git repo with known Python files for chunker/clone/pipeline tests."""
    repo_dir = tmp_path / "fixture_repo"
    repo_dir.mkdir()
    (repo_dir / "functions.py").write_text(FUNCTIONS_PY)
    (repo_dir / "classes.py").write_text(CLASSES_PY)
    (repo_dir / "broken.py").write_text(BROKEN_PY)

    _run_git("init", cwd=repo_dir)
    _run_git("config", "user.email", "test@example.com", cwd=repo_dir)
    _run_git("config", "user.name", "Test", cwd=repo_dir)
    _run_git("add", ".", cwd=repo_dir)
    _run_git("commit", "-m", "initial commit", cwd=repo_dir)

    return repo_dir
```

Create `tests/indexing/test_fixture_repo.py`:

```python
"""Smoke test for the fixture_repo pytest fixture itself."""
from __future__ import annotations

import subprocess
from pathlib import Path


def test_fixture_repo_is_a_real_git_repo_with_expected_files(fixture_repo: Path):
    assert (fixture_repo / ".git").is_dir()
    assert (fixture_repo / "functions.py").exists()
    assert (fixture_repo / "classes.py").exists()
    assert (fixture_repo / "broken.py").exists()

    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=fixture_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "initial commit" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/indexing/test_fixture_repo.py -v`
Expected: FAIL with `fixture 'fixture_repo' not found` (files above don't exist yet)

- [ ] **Step 3: Create the fixture files**

Create both files exactly as shown in Step 1 (there is no separate "minimal implementation" — the fixture and its test are written together since the test only verifies the fixture's own setup).

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/indexing/test_fixture_repo.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add tests/indexing/conftest.py tests/indexing/test_fixture_repo.py
git commit -m "test(indexing): add local git fixture repo for pipeline tests"
```

---

### Task 3: `clone.py` — validated, capped repo cloning

**Files:**
- Create: `coderag_mcp/indexing/clone.py`
- Test: `tests/indexing/test_clone.py`
- Modify: `pyproject.toml` (no new deps needed for this task — `clone.py` uses only `subprocess`, `shutil`, `tempfile`, `urllib.parse` from stdlib)

**Interfaces:**
- Consumes: `IndexingError`, `InvalidRepoURLError`, `CloneTimeoutError`, `RepoTooLargeError` from `coderag_mcp.indexing.models` (Task 1); `fixture_repo` fixture (Task 2).
- Produces: `clone_repo(url: str) -> Path` — clones into a fresh temp directory and returns the path to the cloned repo (a subdirectory named `repo` inside that temp directory). Task 5 (`pipeline.py`) calls this and later removes `clone_repo(...).parent` to clean up.
- Produces: module-level constants `ALLOWED_HOSTS = {"github.com", "gitlab.com"}`, `MAX_REPO_SIZE_MB = 200`, `CLONE_TIMEOUT_S = 60`.

- [ ] **Step 1: Write the failing tests**

Create `tests/indexing/test_clone.py`:

```python
"""Tests for coderag_mcp.indexing.clone.clone_repo."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coderag_mcp.indexing import clone as clone_module
from coderag_mcp.indexing.clone import clone_repo
from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError, RepoTooLargeError


def test_rejects_disallowed_host():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("https://evil.example.com/repo.git")


def test_rejects_bare_ip():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("https://127.0.0.1/repo.git")


def test_rejects_localhost():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("https://localhost/repo.git")


def test_clones_local_fixture_repo(fixture_repo: Path):
    cloned_path = clone_repo(str(fixture_repo))
    try:
        assert cloned_path.is_dir()
        assert (cloned_path / "functions.py").exists()
        assert (cloned_path / "classes.py").exists()
    finally:
        import shutil

        shutil.rmtree(cloned_path.parent, ignore_errors=True)


def test_enforces_size_cap(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(clone_module, "MAX_REPO_SIZE_MB", 0)
    with pytest.raises(RepoTooLargeError):
        clone_repo(str(fixture_repo))


def test_enforces_clone_timeout(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git clone", timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(clone_module.subprocess, "run", _fake_run)
    with pytest.raises(CloneTimeoutError):
        clone_repo(str(fixture_repo))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/indexing/test_clone.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coderag_mcp.indexing.clone'`

- [ ] **Step 3: Write the implementation**

Create `coderag_mcp/indexing/clone.py`:

```python
"""Validated, capped git cloning for the indexing pipeline."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError, RepoTooLargeError

ALLOWED_HOSTS = {"github.com", "gitlab.com"}
MAX_REPO_SIZE_MB = 200
CLONE_TIMEOUT_S = 60


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if parsed.hostname not in ALLOWED_HOSTS:
            raise InvalidRepoURLError(f"host not allowed: {parsed.hostname!r}")
    elif parsed.scheme in ("", "file"):
        # Bare local filesystem paths (used by tests against local fixture
        # repos) never leave the machine, so there is no SSRF surface to
        # allowlist against.
        return
    else:
        raise InvalidRepoURLError(f"unsupported URL scheme: {parsed.scheme!r}")


def _dir_size_mb(path: Path) -> float:
    total_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total_bytes / (1024 * 1024)


def clone_repo(url: str) -> Path:
    """Clone ``url`` into a fresh temp directory and return the cloned repo's path.

    Raises ``InvalidRepoURLError``, ``CloneTimeoutError``, or ``RepoTooLargeError``
    on failure. The caller owns cleanup of the returned path's parent directory.
    """
    _validate_url(url)

    tmpdir = Path(tempfile.mkdtemp(prefix="coderag-clone-"))
    dest = tmpdir / "repo"

    try:
        subprocess.run(
            ["git", "clone", "--depth=1", url, str(dest)],
            check=True,
            capture_output=True,
            timeout=CLONE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise CloneTimeoutError(f"clone of {url!r} exceeded {CLONE_TIMEOUT_S}s") from exc
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise InvalidRepoURLError(f"git clone failed for {url!r}: {stderr}") from exc

    size_mb = _dir_size_mb(dest)
    if size_mb > MAX_REPO_SIZE_MB:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RepoTooLargeError(f"{url!r} is {size_mb:.1f}MB, exceeds {MAX_REPO_SIZE_MB}MB cap")

    return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/indexing/test_clone.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add coderag_mcp/indexing/clone.py tests/indexing/test_clone.py
git commit -m "feat(indexing): add validated, capped repo cloning"
```

---

### Task 4: `chunker.py` — tree-sitter parsing into `Chunk`s

**Files:**
- Modify: `pyproject.toml` (add `tree-sitter` and `tree-sitter-python` to `[project] dependencies`)
- Create: `coderag_mcp/indexing/chunker.py`
- Test: `tests/indexing/test_chunker.py`

**Interfaces:**
- Consumes: `Chunk` from `coderag_mcp.indexing.models` (Task 1); `fixture_repo` fixture (Task 2).
- Produces: `chunk_file(path: Path, repo_url: str, file_path: str) -> list[Chunk]`. Task 5 (`pipeline.py`) calls this once per discovered `.py` file, passing the file's path on disk, the original repo URL, and the file's path relative to the repo root.

- [ ] **Step 1: Add and install dependencies**

Edit `pyproject.toml`, in the `[project] dependencies` list, add two entries after `"mcp>=2.0.0,<3.0.0",`:

```toml
    "tree-sitter>=0.23.0,<0.24.0",
    "tree-sitter-python>=0.23.0,<0.24.0",
```

Run: `./.venv/bin/pip install -e ".[dev]"`
Expected: install succeeds, `tree-sitter` and `tree-sitter-python` show up in `./.venv/bin/pip list`.

- [ ] **Step 2: Write the failing tests**

Create `tests/indexing/test_chunker.py`:

```python
"""Tests for coderag_mcp.indexing.chunker.chunk_file."""
from __future__ import annotations

from pathlib import Path

from coderag_mcp.indexing.chunker import chunk_file

REPO_URL = "https://github.com/example/repo"


def test_extracts_top_level_function(fixture_repo: Path):
    chunks = chunk_file(fixture_repo / "functions.py", REPO_URL, "functions.py")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.symbol_type == "function"
    assert chunk.symbol_name == "add"
    assert chunk.parent_class is None
    assert chunk.repo_url == REPO_URL
    assert chunk.file_path == "functions.py"
    assert chunk.signature == "def add(a: int, b: int) -> int:"
    assert "return a + b" in chunk.source
    assert chunk.start_line == 1
    assert chunk.end_line == 3


def test_extracts_class_and_its_methods(fixture_repo: Path):
    chunks = chunk_file(fixture_repo / "classes.py", REPO_URL, "classes.py")

    class_chunks = [c for c in chunks if c.symbol_type == "class"]
    method_chunks = [c for c in chunks if c.symbol_type == "method"]

    assert len(class_chunks) == 1
    assert class_chunks[0].symbol_name == "Greeter"
    assert class_chunks[0].parent_class is None
    assert "Greets people by name" in class_chunks[0].source

    assert len(method_chunks) == 2
    method_names = {c.symbol_name for c in method_chunks}
    assert method_names == {"__init__", "greet"}
    for method_chunk in method_chunks:
        assert method_chunk.parent_class == "Greeter"


def test_broken_syntax_file_returns_no_chunks_without_raising(fixture_repo: Path):
    chunks = chunk_file(fixture_repo / "broken.py", REPO_URL, "broken.py")
    assert chunks == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/indexing/test_chunker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coderag_mcp.indexing.chunker'`

- [ ] **Step 4: Write the implementation**

Create `coderag_mcp/indexing/chunker.py`:

```python
"""tree-sitter-based extraction of function/class/method chunks from .py files."""
from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from coderag_mcp.indexing.models import Chunk

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode()


def _function_chunk(
    node: Node, source: bytes, repo_url: str, file_path: str, parent_class: str | None
) -> Chunk:
    name_node = node.child_by_field_name("name")
    assert name_node is not None
    full_source = _node_text(node, source)
    signature = full_source.split("\n", 1)[0].rstrip()

    return Chunk(
        repo_url=repo_url,
        file_path=file_path,
        symbol_type="method" if parent_class else "function",
        symbol_name=_node_text(name_node, source),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=signature,
        source=full_source,
        parent_class=parent_class,
    )


def _class_chunk(node: Node, source: bytes, repo_url: str, file_path: str) -> Chunk:
    name_node = node.child_by_field_name("name")
    body_node = node.child_by_field_name("body")
    assert name_node is not None and body_node is not None

    header = source[node.start_byte : body_node.start_byte].decode().rstrip()
    docstring = ""
    if body_node.named_child_count > 0:
        first_stmt = body_node.named_children[0]
        if first_stmt.type == "expression_statement" and first_stmt.named_child_count > 0:
            expr = first_stmt.named_children[0]
            if expr.type == "string":
                docstring = "\n" + _node_text(first_stmt, source)

    return Chunk(
        repo_url=repo_url,
        file_path=file_path,
        symbol_type="class",
        symbol_name=_node_text(name_node, source),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=header,
        source=header + docstring,
        parent_class=None,
    )


def chunk_file(path: Path, repo_url: str, file_path: str) -> list[Chunk]:
    """Parse one .py file and return its function/class/method chunks.

    Returns an empty list (with a logged warning) if the file has syntax
    errors — per-file failures never abort the overall indexing job.
    """
    source = path.read_bytes()
    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source)

    if tree.root_node.has_error:
        logger.warning("skipping %s: syntax errors during parse", file_path)
        return []

    chunks: list[Chunk] = []
    for node in tree.root_node.named_children:
        if node.type == "function_definition":
            chunks.append(_function_chunk(node, source, repo_url, file_path, None))
        elif node.type == "class_definition":
            chunks.append(_class_chunk(node, source, repo_url, file_path))
            class_name = _node_text(node.child_by_field_name("name"), source)
            body_node = node.child_by_field_name("body")
            for child in body_node.named_children:
                if child.type == "function_definition":
                    chunks.append(
                        _function_chunk(child, source, repo_url, file_path, class_name)
                    )
    return chunks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/indexing/test_chunker.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml coderag_mcp/indexing/chunker.py tests/indexing/test_chunker.py
git commit -m "feat(indexing): add tree-sitter chunker for functions/classes/methods"
```

---

### Task 5: `pipeline.py` — orchestration with file-count cap and timeout

**Files:**
- Create: `coderag_mcp/indexing/pipeline.py`
- Test: `tests/indexing/test_pipeline.py`

**Interfaces:**
- Consumes: `clone_repo` from `coderag_mcp.indexing.clone` (Task 3); `chunk_file` from `coderag_mcp.indexing.chunker` (Task 4); `Chunk`, `TooManyFilesError`, `PipelineTimeoutError` from `coderag_mcp.indexing.models` (Task 1); `fixture_repo` fixture (Task 2).
- Produces: `index_repo(repo_url: str) -> list[Chunk]` — the single public entry point for this plan. Later plans (embeddings, REST/MCP wiring) import and call this directly.
- Produces: module-level constants `MAX_FILE_COUNT = 500`, `PIPELINE_TIMEOUT_S = 120`.

- [ ] **Step 1: Write the failing tests**

Create `tests/indexing/test_pipeline.py`:

```python
"""Tests for coderag_mcp.indexing.pipeline.index_repo."""
from __future__ import annotations

from pathlib import Path

import pytest

from coderag_mcp.indexing import pipeline as pipeline_module
from coderag_mcp.indexing.models import PipelineTimeoutError, TooManyFilesError
from coderag_mcp.indexing.pipeline import index_repo


def test_index_repo_returns_expected_chunks(fixture_repo: Path):
    chunks = index_repo(str(fixture_repo))

    symbol_names = {c.symbol_name for c in chunks}
    assert symbol_names == {"add", "Greeter", "__init__", "greet"}

    function_chunk = next(c for c in chunks if c.symbol_name == "add")
    assert function_chunk.repo_url == str(fixture_repo)
    assert function_chunk.file_path == "functions.py"

    # broken.py contributes no chunks, but does not abort the job
    assert all(c.file_path != "broken.py" for c in chunks)


def test_index_repo_cleans_up_temp_dir(fixture_repo: Path):
    chunks = index_repo(str(fixture_repo))
    assert chunks  # sanity: got real chunks
    # Every chunk's file_path is relative, so nothing here references the
    # temp dir directly; instead verify no coderag-clone-* dirs are left in
    # the system temp root after a successful run.
    import glob
    import tempfile

    leftovers = glob.glob(str(Path(tempfile.gettempdir()) / "coderag-clone-*"))
    assert leftovers == []


def test_index_repo_enforces_file_count_cap(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline_module, "MAX_FILE_COUNT", 1)
    with pytest.raises(TooManyFilesError):
        index_repo(str(fixture_repo))


def test_index_repo_enforces_pipeline_timeout(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline_module, "PIPELINE_TIMEOUT_S", -1)
    with pytest.raises(PipelineTimeoutError):
        index_repo(str(fixture_repo))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/indexing/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coderag_mcp.indexing.pipeline'`

- [ ] **Step 3: Write the implementation**

Create `coderag_mcp/indexing/pipeline.py`:

```python
"""Orchestrates clone -> discover .py files -> chunk into the pipeline's public entry point."""
from __future__ import annotations

import shutil
import time

from coderag_mcp.indexing.chunker import chunk_file
from coderag_mcp.indexing.clone import clone_repo
from coderag_mcp.indexing.models import Chunk, PipelineTimeoutError, TooManyFilesError

MAX_FILE_COUNT = 500
PIPELINE_TIMEOUT_S = 120


def index_repo(repo_url: str) -> list[Chunk]:
    """Clone, parse, and chunk a repo. Raises IndexingError subclasses on job-level failure."""
    start = time.monotonic()
    repo_dir = clone_repo(repo_url)

    try:
        py_files = sorted(repo_dir.rglob("*.py"))
        if len(py_files) > MAX_FILE_COUNT:
            raise TooManyFilesError(
                f"{repo_url!r} has {len(py_files)} .py files, exceeds {MAX_FILE_COUNT} cap"
            )

        chunks: list[Chunk] = []
        for py_file in py_files:
            if time.monotonic() - start > PIPELINE_TIMEOUT_S:
                raise PipelineTimeoutError(
                    f"indexing {repo_url!r} exceeded {PIPELINE_TIMEOUT_S}s"
                )
            file_path = str(py_file.relative_to(repo_dir))
            chunks.extend(chunk_file(py_file, repo_url, file_path))
        return chunks
    finally:
        shutil.rmtree(repo_dir.parent, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/indexing/test_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full test suite**

Run: `./.venv/bin/pytest -v`
Expected: all tests pass, including the pre-existing `tests/test_health.py` and `tests/test_mcp_server.py`.

- [ ] **Step 6: Commit**

```bash
git add coderag_mcp/indexing/pipeline.py tests/indexing/test_pipeline.py
git commit -m "feat(indexing): add index_repo pipeline orchestration"
```

---

## Plan Self-Review Notes

- **Spec coverage:** `models.py` (Task 1) covers "Components > models.py"; the fixture (Task 2) covers "Testing > Fixture"; `clone.py` (Task 3) covers "Components > clone.py" and the allowlist/size/timeout rows of "Error handling"; `chunker.py` (Task 4) covers "Components > chunker.py" including the function/class/method granularity and per-file-failure behavior; `pipeline.py` (Task 5) covers "Components > pipeline.py" including the file-count cap and pipeline timeout. "Dependencies added" is covered in Task 4, Step 1.
- **Type consistency:** `clone_repo(url: str) -> Path` (Task 3) is called by `pipeline.index_repo` (Task 5) exactly as defined. `chunk_file(path: Path, repo_url: str, file_path: str) -> list[Chunk]` (Task 4) is called by `pipeline.index_repo` (Task 5) with matching argument order and types. `Chunk` fields are used identically across Tasks 1, 4, and 5.
- **No placeholders:** every step has runnable code, not descriptions.
