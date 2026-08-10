# Local Robustness + nanoLoop-Style Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make coderag-mcp genuinely clone-and-run-locally friendly (nanoLoop-style)
and raise the backend + AI-orchestrator layer's robustness bar, per
`docs/superpowers/specs/2026-08-10-local-robustness-design.md`.

**Architecture:** Structured JSON logging and fail-fast startup config validation land
first (foundational, everything else logs through them); then Voyage retry/backoff and
an explicit orchestrator timeout hardening the two slowest/flakiest external calls; then
a real, dry-run-verified README quickstart + `.env.example` ties it together for a
first-time cloner.

**Tech Stack:** Python stdlib `logging` (no new dependency), `voyageai.error`'s existing
exception hierarchy, `asyncio.timeout` (3.11+ stdlib).

## Global Constraints

- No new dependencies for logging — a custom `logging.Formatter` subclass against
  stdlib `logging`, not a third-party JSON-logging package.
- Voyage retry only on transient `voyageai.error` types (confirmed against the
  installed SDK while writing this plan): `APIConnectionError`, `RateLimitError`,
  `ServerError`, `ServiceUnavailableError`, `Timeout`, `TryAgain`. Every other
  exception (including `AuthenticationError`, `InvalidRequestError`,
  `MalformedRequestError`, the generic `APIError`, and anything outside
  `voyageai.error` entirely) fails immediately, no retry.
- `embed_batch`'s retry sleep uses `time.sleep`, never `asyncio.sleep` — it's a sync
  function that already runs inside `asyncio.to_thread` at every call site; sleeping
  synchronously there blocks only that worker thread, not the event loop.
- `ask()`'s timeout is a parameter (`timeout_s: float = 180.0`), not a hardcoded
  constant, so tests can override it instead of waiting the real duration.
- `CODERAG_API_KEY` is never validated at startup — empty/unset is a supported
  dev-mode value (existing, documented behavior), not a misconfiguration to fail on.
- `validate_settings()` and `configure_logging()` are each called from exactly two
  places — `api/main.py`'s `create_app()` and `mcp_server/server.py`'s `_lifespan` —
  no duplicated logic between the two transports, matching this project's established
  core-plus-adapters shape (see `api/auth.py`'s `validate_api_key` for precedent).
- Full test suite (currently 71/71) must stay green after every task.
- The README quickstart (Task 5) is dry-run tested for real (fresh clone, steps run
  as written) before being considered done — not documented without being run.

---

### Task 1: Structured JSON logging

**Files:**
- Create: `coderag_mcp/logging_config.py`
- Modify: `coderag_mcp/api/main.py`
- Modify: `coderag_mcp/mcp_server/server.py`
- Test: `tests/test_logging_config.py`

**Interfaces:**
- Produces: `configure_logging(level: int = logging.INFO) -> None` in
  `coderag_mcp/logging_config.py`. Tasks 3-4 use plain `logging.getLogger(__name__)`
  calls in their own modules — no other function from this task is consumed
  elsewhere; the point of this task is that *any* logging anywhere in the process
  becomes JSON-formatted once `configure_logging()` has run.

- [ ] **Step 1: Write the failing test**

Create `tests/test_logging_config.py`:

```python
"""Tests for coderag_mcp.logging_config."""
from __future__ import annotations

import json
import logging

from coderag_mcp.logging_config import configure_logging


def test_configure_logging_emits_one_json_object_per_line(capsys):
    configure_logging()
    logger = logging.getLogger("test.logging_config")

    logger.info("hello world", extra={"repo_url": "https://github.com/a/b"})

    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logging_config"
    assert payload["repo_url"] == "https://github.com/a/b"
    assert "timestamp" in payload


def test_configure_logging_includes_exception_traceback(capsys):
    configure_logging()
    logger = logging.getLogger("test.logging_config.exc")

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("something failed")

    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    assert "ValueError: boom" in payload["exception"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_logging_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'coderag_mcp.logging_config'`)

- [ ] **Step 3: Write `coderag_mcp/logging_config.py`**

```python
"""Structured JSON logging, installed once at process startup.

Standard-library `logging` only - no new dependency. `JSONFormatter` emits one
JSON object per log line (timestamp, level, logger name, message, plus any
`extra=` fields the caller passed), which is far easier to grep/parse than
free-text log lines once this project's `except Exception` blocks and
external-API call sites (Voyage, the orchestrator) start actually logging.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

# The set of attributes every LogRecord carries regardless of what was logged -
# used to separate "extra" fields (anything the caller passed via `extra={...}`)
# from LogRecord's own bookkeeping attributes. Confirmed against a real
# LogRecord's __dict__ keys while writing this plan, not guessed.
_STANDARD_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Install JSON-formatted logging on the root logger. Call once, at startup -
    safe to call more than once (e.g. once from api/main.py's create_app() and
    once from mcp_server/server.py's _lifespan in the same process): each call
    clears and reinstalls the same handler, so it's idempotent, not additive."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_logging_config.py -v`
Expected: PASS

- [ ] **Step 5: Wire `configure_logging()` into `api/main.py`'s `create_app()`**

Edit `coderag_mcp/api/main.py`. Add the import:

```python
from coderag_mcp.logging_config import configure_logging
```

Inside `create_app()`, as the very first line of the function body (before
`settings = get_settings()`):

```python
def create_app() -> FastAPI:
    """..."""  # existing docstring unchanged
    configure_logging()
    settings = get_settings()
    ...
```

- [ ] **Step 6: Wire `configure_logging()` into `mcp_server/server.py`'s `_lifespan`**

Edit `coderag_mcp/mcp_server/server.py`. Add the import:

```python
from coderag_mcp.logging_config import configure_logging
```

Inside `_lifespan`, as the first line of the function body:

```python
@asynccontextmanager
async def _lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    configure_logging()
    settings = get_settings()
    ...
```

- [ ] **Step 7: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (73/73 — 71 existing + 2 new)

- [ ] **Step 8: Commit**

```bash
git add coderag_mcp/logging_config.py coderag_mcp/api/main.py coderag_mcp/mcp_server/server.py \
  tests/test_logging_config.py
git commit -m "feat: add structured JSON logging, wired into both startup paths"
```

---

### Task 2: Startup config validation

**Files:**
- Modify: `coderag_mcp/config.py`
- Modify: `coderag_mcp/api/main.py`
- Modify: `coderag_mcp/mcp_server/server.py`
- Modify: `tests/conftest.py`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_config.py` (new)

**Interfaces:**
- Consumes: `configure_logging` (Task 1) - already wired into both call sites this
  task also touches; this task adds one more line to each, no conflict.
- Produces: `validate_settings(settings: Settings) -> None` in
  `coderag_mcp/config.py`. No later task consumes it directly.

**Why `tests/conftest.py` and the CI workflow both need a change:** `validate_settings`
raises if `VOYAGE_API_KEY` is empty, and it's called from `create_app()` - which runs
at *import time* (`app = create_app()` at the bottom of `api/main.py`, executed the
moment anything does `from coderag_mcp.api.main import app`, which `tests/conftest.py`
already does). Every test in this project's suite mocks `voyageai.Client` and never
makes a real Voyage call, so they don't need a *real* key - but without a fallback,
this task would break the entire suite in any environment without a real
`VOYAGE_API_KEY` configured, including the GitHub Actions CI workflow added earlier
(no secret configured there) and a fresh clone with no `.env` yet. Fix: `conftest.py`
sets a dummy key via `os.environ.setdefault(...)` before importing `api.main` - this
only takes effect if `VOYAGE_API_KEY` isn't already a real *exported shell* env var
(confirmed empirically while writing this plan: pydantic-settings gives actual
`os.environ` priority over `.env` file contents, and `.env` file values never populate
`os.environ` themselves - so `setdefault` correctly leaves a developer's real
*exported* key alone, while still activating whenever the only source is an
`.env` file, which is exactly the case tests should never depend on anyway).

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for coderag_mcp.config.validate_settings."""
from __future__ import annotations

import pytest

from coderag_mcp.config import Settings, validate_settings


def test_validate_settings_raises_when_voyage_api_key_missing():
    settings = Settings(voyage_api_key="")
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        validate_settings(settings)


def test_validate_settings_passes_when_voyage_api_key_set():
    settings = Settings(voyage_api_key="test-key")
    validate_settings(settings)  # must not raise


def test_validate_settings_does_not_require_coderag_api_key():
    """CODERAG_API_KEY empty/unset is a supported dev-mode value, not a
    misconfiguration - validate_settings must not raise on it being empty."""
    settings = Settings(voyage_api_key="test-key", api_key="")
    validate_settings(settings)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL (`ImportError: cannot import name 'validate_settings'`)

- [ ] **Step 3: Write `validate_settings` in `coderag_mcp/config.py`**

Add to `coderag_mcp/config.py`, after the `Settings` class and before
`get_settings`:

```python
def validate_settings(settings: Settings) -> None:
    """Raise RuntimeError with an actionable message if a required setting is
    missing. Called once at startup by both api/main.py's create_app() and
    mcp_server/server.py's _lifespan - fails fast rather than accepting requests
    and failing confusingly on the first real Voyage call.

    CODERAG_API_KEY is intentionally NOT validated here: empty/unset is a
    supported dev-mode value (see api/auth.py's validate_api_key), not a
    misconfiguration.
    """
    if not settings.voyage_api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY is required - set it in .env or the environment. "
            "See README.md's Quickstart."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Wire `validate_settings` into `api/main.py`'s `create_app()`**

Edit `coderag_mcp/api/main.py`. Add to the import from `coderag_mcp.config`:

```python
from coderag_mcp.config import get_settings, validate_settings
```

Inside `create_app()`, right after `settings = get_settings()`:

```python
    configure_logging()
    settings = get_settings()
    validate_settings(settings)
```

- [ ] **Step 6: Wire `validate_settings` into `mcp_server/server.py`'s `_lifespan`**

Edit `coderag_mcp/mcp_server/server.py`. Add to the import from
`coderag_mcp.config`:

```python
from coderag_mcp.config import get_settings, validate_settings
```

Inside `_lifespan`, right after `settings = get_settings()`:

```python
    configure_logging()
    settings = get_settings()
    validate_settings(settings)
```

- [ ] **Step 7: Add the dummy-key fallback to `tests/conftest.py`**

Edit `tests/conftest.py`. It must be the *first* thing that runs, before the
`from coderag_mcp.api.main import app` import (Python executes top-level
statements in file order):

```python
"""Shared pytest fixtures."""
from __future__ import annotations

import os

# Tests never make a real Voyage API call (voyageai.Client is always mocked),
# so they don't need a real key - but api.main.create_app() now calls
# validate_settings(), which raises if VOYAGE_API_KEY is unset. setdefault()
# only takes effect if the var isn't already a real exported shell env var,
# so a developer's real key (if actually exported, not just in .env) still wins.
os.environ.setdefault("VOYAGE_API_KEY", "test-voyage-key-not-a-real-key")

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
```

- [ ] **Step 8: Run the full suite to confirm nothing broke**

Run: `./.venv/bin/pytest -v`
Expected: PASS (76/76 — 73 from Task 1 + 3 new)

- [ ] **Step 9: Confirm CI would pass without a real key configured**

CI has no `VOYAGE_API_KEY` secret and no `.env` file, so it depends entirely on
`conftest.py`'s fallback from Step 7 (no separate CI workflow change is needed -
this step is a verification, not a code change). Simulate it locally:

```bash
env -u VOYAGE_API_KEY -u CODERAG_API_KEY ./.venv/bin/pytest -v
```

Expected: PASS, identical to Step 8 — proves the suite doesn't depend on this
machine's real `.env` file. If this fails while Step 8 passed, the dummy-key
fallback in `conftest.py` isn't taking effect before `api.main` is imported
somewhere else in the suite — find that earlier import and fix the ordering
before proceeding.

- [ ] **Step 10: Commit**

```bash
git add coderag_mcp/config.py coderag_mcp/api/main.py coderag_mcp/mcp_server/server.py \
  tests/conftest.py tests/test_config.py
git commit -m "feat: fail fast at startup if VOYAGE_API_KEY is missing"
```

---

### Task 3: Voyage retry/backoff

**Files:**
- Modify: `coderag_mcp/embeddings/voyage.py`
- Test: `tests/embeddings/test_voyage.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2 directly (uses plain `logging.getLogger(__name__)`,
  which becomes JSON-formatted once Task 1's `configure_logging()` has run somewhere
  in the process — no import needed here).
- Produces: `embed_batch(texts, *, input_type="document")` — signature unchanged.
  No later task depends on new internals.

**Exception classes confirmed against the installed `voyageai` SDK while writing
this plan** (constructor signature for all of them:
`__init__(self, message=None, http_body=None, http_status=None, json_body=None,
headers=None, code=None)` — every one is constructible with just `message=...` for
tests):
- Retryable: `voyageai.error.APIConnectionError`, `RateLimitError`, `ServerError`,
  `ServiceUnavailableError`, `Timeout`, `TryAgain`.
- Not retryable (fail immediately): `AuthenticationError`, `InvalidRequestError`,
  `MalformedRequestError`, the generic `APIError`, and anything not a
  `voyageai.error.VoyageError` subclass at all.

- [ ] **Step 1: Write the failing tests**

Add to `tests/embeddings/test_voyage.py`:

```python
import pytest
import voyageai.error

from coderag_mcp.embeddings.voyage import embed_batch


@pytest.mark.parametrize(
    "error_cls",
    [
        voyageai.error.APIConnectionError,
        voyageai.error.RateLimitError,
        voyageai.error.ServerError,
        voyageai.error.ServiceUnavailableError,
        voyageai.error.Timeout,
        voyageai.error.TryAgain,
    ],
)
def test_embed_batch_retries_transient_errors_and_succeeds(error_cls, monkeypatch):
    fake_result = MagicMock(embeddings=[[0.1, 0.2]])
    call_count = {"n": 0}

    def flaky_embed(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise error_cls(message="transient failure")
        return fake_result

    monkeypatch.setattr("coderag_mcp.embeddings.voyage.time.sleep", lambda _: None)
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.side_effect = flaky_embed

        result = embed_batch(["a"], input_type="document")

    assert result == [[0.1, 0.2]]
    assert call_count["n"] == 3


@pytest.mark.parametrize(
    "error_cls",
    [
        voyageai.error.AuthenticationError,
        voyageai.error.InvalidRequestError,
        voyageai.error.MalformedRequestError,
        voyageai.error.APIError,
    ],
)
def test_embed_batch_does_not_retry_non_transient_errors(error_cls, monkeypatch):
    call_count = {"n": 0}

    def always_fails(*args, **kwargs):
        call_count["n"] += 1
        raise error_cls(message="not retryable")

    monkeypatch.setattr("coderag_mcp.embeddings.voyage.time.sleep", lambda _: None)
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.side_effect = always_fails

        with pytest.raises(error_cls):
            embed_batch(["a"], input_type="document")

    assert call_count["n"] == 1


def test_embed_batch_raises_after_exhausting_all_retries(monkeypatch):
    call_count = {"n": 0}

    def always_times_out(*args, **kwargs):
        call_count["n"] += 1
        raise voyageai.error.Timeout(message="still timing out")

    monkeypatch.setattr("coderag_mcp.embeddings.voyage.time.sleep", lambda _: None)
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.side_effect = always_times_out

        with pytest.raises(voyageai.error.Timeout):
            embed_batch(["a"], input_type="document")

    assert call_count["n"] == 3
```

Check the top of `tests/embeddings/test_voyage.py` already has
`from unittest.mock import MagicMock, patch` — add it if not present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/embeddings/test_voyage.py -v`
Expected: FAIL (no retry logic yet — the flaky-then-succeeds test fails on the
first raised exception; the non-retry tests pass by accident since there's
nothing to retry yet, but re-run after Step 3 to confirm they still pass for
the *right* reason)

- [ ] **Step 3: Add retry/backoff to `embed_batch`**

Replace `coderag_mcp/embeddings/voyage.py` entirely:

```python
"""Voyage AI embedding client for code chunks."""
from __future__ import annotations

import logging
import time

import voyageai
import voyageai.error

from coderag_mcp.config import get_settings

MODEL = "voyage-code-3"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1.0, 2.0)  # sleep before attempt 2, then before attempt 3

_RETRYABLE_ERRORS = (
    voyageai.error.APIConnectionError,
    voyageai.error.RateLimitError,
    voyageai.error.ServerError,
    voyageai.error.ServiceUnavailableError,
    voyageai.error.Timeout,
    voyageai.error.TryAgain,
)

logger = logging.getLogger(__name__)

_client: voyageai.Client | None = None


def _get_client() -> voyageai.Client:
    """Lazily initialize and return the shared Voyage client."""
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

    Retries up to MAX_ATTEMPTS times, with exponential backoff, on transient
    voyageai.error types only (connection/timeout/rate-limit/server errors) -
    anything else (auth failures, malformed requests) fails immediately, since
    retrying those wastes time and can't succeed.
    """
    client = _get_client()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = client.embed(texts, model=MODEL, input_type=input_type)
            return result.embeddings
        except _RETRYABLE_ERRORS as exc:
            if attempt == MAX_ATTEMPTS:
                logger.error(
                    "embed_batch failed after %d attempts: %s",
                    MAX_ATTEMPTS,
                    exc,
                    extra={"attempt": attempt, "error_type": type(exc).__name__},
                )
                raise
            delay = BACKOFF_SECONDS[attempt - 1]
            logger.warning(
                "embed_batch attempt %d/%d failed, retrying in %.0fs: %s",
                attempt,
                MAX_ATTEMPTS,
                delay,
                exc,
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            time.sleep(delay)

    # Unreachable: the loop always returns or raises above.
    raise AssertionError("unreachable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/embeddings/test_voyage.py -v`
Expected: PASS (all tests, including the pre-existing ones from before this task)

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (76 + 11 new = 87)

- [ ] **Step 6: Commit**

```bash
git add coderag_mcp/embeddings/voyage.py tests/embeddings/test_voyage.py
git commit -m "feat: retry embed_batch with exponential backoff on transient Voyage errors"
```

---

### Task 4: Orchestrator timeout

**Files:**
- Modify: `coderag_mcp/orchestrator/ask.py`
- Test: `tests/orchestrator/test_ask.py`

**Interfaces:**
- Produces: `ask(conn, repo_id, repo_url, question, *, timeout_s: float = 180.0) ->
  str` — signature gains one new keyword-only parameter with a default; every
  existing caller (`api/ask_route.py`, `mcp_server/server.py`'s `ask_repo`) keeps
  working unchanged since they don't pass it. No later task depends on this.

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestrator/test_ask.py`:

```python
async def _hanging_query_stream(*, prompt, options):
    # Never yields - simulates a stuck claude CLI subprocess.
    await asyncio.sleep(10)
    yield  # pragma: no cover - unreachable, makes this a generator function


@pytest.mark.asyncio
async def test_ask_raises_timeout_error_if_query_never_completes(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_hanging_query_stream),
    ):
        with pytest.raises(TimeoutError):
            await ask(
                conn,
                repo_id=1,
                repo_url="https://github.com/a/b",
                question="how does auth work?",
                timeout_s=0.05,
            )
```

Add `import asyncio` to the top of `tests/orchestrator/test_ask.py` if not
already present (check first).

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py::test_ask_raises_timeout_error_if_query_never_completes -v`
Expected: FAIL (`TypeError: ask() got an unexpected keyword argument 'timeout_s'`)

- [ ] **Step 3: Add the timeout to `ask()`**

Replace `coderag_mcp/orchestrator/ask.py` entirely:

```python
"""Runs the single-agent orchestrator behind ask()."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from coderag_mcp.indexing import clone
from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT
from coderag_mcp.orchestrator.tools import build_search_server

logger = logging.getLogger(__name__)


async def ask(
    conn: sqlite3.Connection,
    repo_id: int,
    repo_url: str,
    question: str,
    *,
    timeout_s: float = 180.0,
) -> str:
    search_server = build_search_server(conn, repo_id)

    repo_dir = await asyncio.to_thread(clone.clone_repo, repo_url, allow_local_paths=False)
    start = time.monotonic()
    logger.info(
        "orchestrator query starting",
        extra={"repo_url": repo_url, "question_length": len(question)},
    )
    try:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            allowed_tools=["mcp__search__search_code", "Read", "Grep", "Glob"],
            mcp_servers={"search": search_server},
        )

        answer_parts: list[str] = []
        try:
            async with asyncio.timeout(timeout_s):
                async for message in query(prompt=question, options=options):
                    if not isinstance(message, AssistantMessage):
                        continue
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            answer_parts.append(block.text)
        except TimeoutError:
            logger.error(
                "orchestrator query timed out after %.0fs",
                timeout_s,
                extra={"repo_url": repo_url, "timeout_s": timeout_s},
            )
            raise

        logger.info(
            "orchestrator query completed",
            extra={"repo_url": repo_url, "duration_s": time.monotonic() - start},
        )
        return "".join(answer_parts)
    finally:
        await asyncio.to_thread(clone.cleanup_clone, repo_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py -v`
Expected: PASS (both the new test and the pre-existing
`test_ask_concatenates_streamed_text_and_scopes_cwd`, which doesn't pass
`timeout_s` and so uses the 180s default — its mocked `query()` resolves
instantly, well under that)

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (87 + 1 new = 88)

- [ ] **Step 6: Commit**

```bash
git add coderag_mcp/orchestrator/ask.py tests/orchestrator/test_ask.py
git commit -m "feat: add an explicit timeout to the orchestrator's query() call"
```

---

### Task 5: README quickstart + `.env.example`

**Files:**
- Create: `.env.example`
- Modify: `README.md`

**Interfaces:**
- None — this task is documentation only, consumed by humans, not by later tasks or
  code.

**Context:** `README.md` already has `Setup`/`Run`/`Auth`/`MCP server`/`Test`
sections (added by an earlier plan's final-review fix wave) — this task doesn't
start from scratch, it adds a `.env.example` file, folds the existing scattered
setup steps into one linear "Quickstart" section, and adds the one thing that's
genuinely missing: how to register this project as an MCP server in Claude Code.

- [ ] **Step 1: Create `.env.example`**

```bash
# Required: embeds code chunks and search queries via Voyage AI's voyage-code-3.
# Get a key at https://dash.voyageai.com/
VOYAGE_API_KEY=

# Optional: if set, /ask and /mcp both require this exact value as the
# X-API-Key header on every request. Leave empty to disable auth (dev mode,
# the default) - fine for local use, but set this before exposing the server
# to anything other than localhost.
CODERAG_API_KEY=
```

- [ ] **Step 2: Confirm the exact `claude mcp add` syntax against the installed CLI**

Run: `claude mcp add --help`

Confirmed while writing this plan (re-verify if your installed CLI version
differs): the command is
`claude mcp add --transport http <name> <url> [--header "X-Api-Key: <value>"]`.
Verified end-to-end against a real running instance of this project's server
(both without a key, and with `CODERAG_API_KEY` set + `--header "X-Api-Key:
..."`) — both connect successfully per `claude mcp list`'s `✔ Connected` status.

- [ ] **Step 3: Rewrite `README.md`'s setup sections into one Quickstart**

Replace `README.md`'s existing `## Setup` and `## Run` sections (keep `##
Inspiration`, `## Auth`, `## MCP server`, and `## Test` where they are — this
step only touches Setup/Run) with:

```markdown
## Quickstart

```bash
git clone https://github.com/<you>/coderag-mcp.git
cd coderag-mcp
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"

cp .env.example .env
# edit .env: set VOYAGE_API_KEY (see .env.example for where to get one)

./.venv/bin/uvicorn coderag_mcp.api.main:app --reload
```

The server refuses to start if `VOYAGE_API_KEY` is missing, with a message
telling you what's wrong - see `coderag_mcp/config.py`'s `validate_settings`.

Ask it a question about any public GitHub/GitLab repo (indexes it on first
use):

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/pallets/flask", "question": "How does routing work?"}'
```

All other settings (`CODERAG_PUBLIC_HOST`, `CODERAG_SQLITE_DB_PATH`,
`CODERAG_ALLOWED_HOSTS`, etc.) are optional and have sensible defaults — see
`coderag_mcp/config.py`. Note the `CODERAG_` prefix: every setting except
`VOYAGE_API_KEY` is only read from its `CODERAG_`-prefixed env var name, so a
generic env var like `ALLOWED_HOSTS` (common on PaaS platforms) can't
accidentally override it.
```

- [ ] **Step 4: Add an MCP-client registration example to the existing `## MCP server` section**

Find `README.md`'s existing `## MCP server` section (it currently only lists
the tools). Add this immediately after the tool list, before `## Test`:

```markdown
### Using it as an MCP server in Claude Code

With the server running (see Quickstart above):

```bash
claude mcp add --transport http coderag http://localhost:8000/mcp/
```

If `CODERAG_API_KEY` is set, pass it as a header:

```bash
claude mcp add --transport http coderag http://localhost:8000/mcp/ \
  --header "X-Api-Key: your-chosen-secret"
```

Verify it connected: `claude mcp list` should show `coderag` as `✔ Connected`.
Claude Code can now call `index_repo`, `search_code`, and `ask_repo` directly.
```

- [ ] **Step 5: Dry-run the entire quickstart in a fresh clone**

This is the step that makes this task done, not just written. Run every
command below for real, in order, and confirm each one behaves as documented
— fix `README.md`/`​.env.example` immediately if anything doesn't match:

```bash
cd /tmp
rm -rf coderag-mcp-dryrun
git clone /Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp coderag-mcp-dryrun
cd coderag-mcp-dryrun
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

Edit the fresh clone's `.env` and paste in a real `VOYAGE_API_KEY` (reuse the
one from this repo's own `.env` — check with the human operating this session
if you can't read it directly, don't invent a fake one for this step, it must
actually start the server for real):

```bash
./.venv/bin/uvicorn coderag_mcp.api.main:app --port 8199 &
sleep 2
curl -X POST http://localhost:8199/ask \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/pallets/flask", "question": "How does routing work?"}'
```

Expected: a real JSON `{"answer": "..."}` response (this will take ~30-60s the
first time, since it indexes flask's repo). Then test the MCP registration
step too:

```bash
claude mcp add --transport http coderag-dryrun http://localhost:8199/mcp/
claude mcp list  # confirm coderag-dryrun shows "✔ Connected"
claude mcp remove coderag-dryrun
```

Then clean up:

```bash
kill %1  # stops the background uvicorn from this dry run
cd /Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp
rm -rf /tmp/coderag-mcp-dryrun
```

If anything in this dry run didn't match what `README.md` says, fix
`README.md`/`.env.example` now and re-run the affected steps before moving on
— do not commit an unverified quickstart.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: PASS (88/88 — this task adds no new automated tests, it's
documentation, verified manually in Step 5)

- [ ] **Step 7: Commit**

```bash
git add .env.example README.md
git commit -m "docs: add a real, dry-run-verified README quickstart + .env.example"
```

---

## Final check

After Task 5, run `./.venv/bin/pytest -v` once more from the repo root and confirm
the full suite (88/88) passes before moving to
`superpowers:finishing-a-development-branch`.
