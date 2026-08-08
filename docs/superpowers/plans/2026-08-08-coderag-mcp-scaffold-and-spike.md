# CodeRAG-MCP Scaffold + MCP Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the new `coderag-mcp` repository with a minimal FastAPI scaffold, then de-risk the single riskiest piece of the whole project — an MCP server reachable over Streamable HTTP — before any RAG logic is built.

**Architecture:** A brand-new standalone git repo (separate from nanoLoop, per the approved design) at `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp`. Task 1 creates the repo and a bare FastAPI app with a `/health` endpoint. Task 2 adds an MCP server (one dummy `ping` tool) mounted into the same FastAPI app at `/mcp` via the official `mcp` Python SDK's Streamable HTTP transport, verified end-to-end with a real MCP client over a real running server — not mocked. This is the first of several plans; later plans (indexing, embeddings/store, RAG endpoint, real MCP tools, auth/production-readiness, deploy) build on this once it's proven solid, per the Build Order section of the approved design spec.

**Tech Stack:** Python 3.11+, FastAPI, `mcp` (official Model Context Protocol Python SDK), `pydantic-settings`, `uvicorn`, pytest (+ `pytest-asyncio`, `httpx`).

**Source design doc:** `docs/superpowers/specs/2026-08-08-coderag-mcp-backend-design.md` in the nanoLoop repo (this plan implements only the "MCP server spike first" and initial scaffold steps of that design's Build Order).

## Global Constraints

- New, standalone git repository — do not create these files inside the nanoLoop repo.
- Python 3.11+, FastAPI-based, no LangChain/DeepAgents/OpenShell dependency (this is not an agent harness).
- MCP transport is Streamable HTTP, mounted into the same FastAPI service at `/mcp` — not stdio, not a separate process.
- No RAG/indexing/embeddings logic in this plan — that is explicitly out of scope, covered by later plans.
- README must credit nanoLoop as a design inspiration (patterns only, not code) per the approved design doc's "Why a new repo, not an extension of nanoLoop" section.

---

### Task 1: Initialize the repo and a minimal FastAPI scaffold

**Files:**
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/pyproject.toml`
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/.gitignore`
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/README.md`
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/coderag_mcp/__init__.py`
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/coderag_mcp/config.py`
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/coderag_mcp/api/__init__.py`
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/coderag_mcp/api/main.py`
- Test: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/tests/__init__.py`
- Test: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/tests/conftest.py`
- Test: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/tests/test_health.py`

**Interfaces:**
- Consumes: nothing (first task, fresh repo).
- Produces: a FastAPI app object at `coderag_mcp.api.main.app`, and `coderag_mcp.config.get_settings() -> Settings`. Task 2 imports `app` from `coderag_mcp.api.main` and extends it (mounts `/mcp` onto it) — it must remain a plain `FastAPI()` instance at that import path.

- [x] **Step 1: Create the repo directory and initialize git**

```bash
mkdir -p /Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp
cd /Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp
git init
```

- [x] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "coderag-mcp"
version = "0.1.0"
description = "Code-aware RAG backend, served over REST and MCP (Streamable HTTP)."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "pydantic-settings>=2.6.0",
    "mcp>=1.2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24.0", "httpx>=0.27.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["coderag_mcp"]
```

- [x] **Step 3: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.env
```

- [x] **Step 4: Write `README.md`**

```markdown
# CodeRAG-MCP

Code-aware RAG backend: indexes public repositories with AST-aware chunking
(tree-sitter), stores embeddings in Postgres/pgvector, and answers questions
about the code with file:line citations. Served both as a REST API and as
an MCP server (Streamable HTTP), so it can be queried directly or plugged
into any MCP client (Claude Desktop, Claude.ai connectors, etc.).

**Status:** early scaffold — see the full design doc for architecture,
decisions, and roadmap.

## Inspiration

Design patterns in this project are inspired by
[nanoLoop](https://github.com/ismaelfaro/nanoLoop), an autonomous
engineering harness: the default-deny/explicit-allowlist approach to
security, the `pending → active → done/blocked`-style job state machine,
and the env-var-driven client factory pattern. No code is shared — nanoLoop
is a LangChain/DeepAgents agent harness, this is a RAG/MCP service, with
different stacks.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

## Run

```bash
./.venv/bin/uvicorn coderag_mcp.api.main:app --reload
```

## Test

```bash
./.venv/bin/pytest -v
```
```

- [x] **Step 5: Write `coderag_mcp/__init__.py`**

```python
"""CodeRAG-MCP: code-aware RAG backend, served over REST and MCP."""

__version__ = "0.1.0"
```

- [x] **Step 6: Write `coderag_mcp/config.py`**

```python
"""Typed application settings, loaded from environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "coderag-mcp"


def get_settings() -> Settings:
    return Settings()
```

- [x] **Step 7: Write `coderag_mcp/api/__init__.py`**

```python
"""FastAPI application package."""
```

- [x] **Step 8: Write `coderag_mcp/api/main.py`**

```python
"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="CodeRAG-MCP")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [x] **Step 9: Write the test files**

`tests/__init__.py`:

```python
```

(empty file — marks `tests/` as a package)

`tests/conftest.py`:

```python
"""Shared pytest fixtures."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
```

`tests/test_health.py`:

```python
"""Health endpoint smoke test."""
from __future__ import annotations


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [x] **Step 10: Create the venv and install**

```bash
cd /Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -e ".[dev]"
```

- [x] **Step 11: Run the test to verify it passes**

Run: `./.venv/bin/pytest -v`
Expected: `tests/test_health.py::test_health_returns_ok PASSED` (1 passed).

- [x] **Step 12: Commit**

```bash
cd /Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp
git add pyproject.toml .gitignore README.md coderag_mcp tests
git commit -m "Initial scaffold: FastAPI app with /health endpoint"
```

---

### Task 2: MCP server spike — one tool, reachable over Streamable HTTP, verified with a real client

**Files:**
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/coderag_mcp/mcp_server/__init__.py`
- Create: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/coderag_mcp/mcp_server/server.py`
- Modify: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/coderag_mcp/api/main.py`
- Test: `/Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `coderag_mcp.api.main.app` (the plain `FastAPI()` instance from Task 1), which this task mounts the MCP app onto.
- Produces: `coderag_mcp.mcp_server.server.mcp` (a `FastMCP` instance with one tool, `ping`), reachable at `POST/GET http://<host>/mcp` once the app is served. Later plans add the real tools (`index_repo`, `search_code`, `ask_repo`) to this same `mcp` object — they do not need to touch the mounting/lifespan wiring again.

**Important — this is the highest-uncertainty step in the whole project.** The `mcp` Python SDK is young and its exact API surface can differ between versions. The code below reflects the SDK's documented pattern for mounting a `FastMCP` server's Streamable HTTP ASGI app into an existing FastAPI app (sharing its lifespan so the MCP session manager starts/stops correctly). If any call below doesn't match what's actually installed, inspect the installed package to find the current equivalent — do not silently skip verification:

```bash
./.venv/bin/python -c "import mcp; print(mcp.__version__)"
./.venv/bin/python -c "from mcp.server.fastmcp import FastMCP; help(FastMCP.streamable_http_app)"
```

Adapt the implementation to match the real installed API while preserving the target behavior (one tool, reachable over Streamable HTTP at `/mcp`, verified end-to-end by a real `mcp` client call in Step 5's test) — and note any deviation from the code below in your report.

- [x] **Step 1: Write the failing test**

Create `tests/test_mcp_server.py`:

```python
"""End-to-end verification that the MCP server is reachable over Streamable HTTP.

This is the project's highest-risk integration point, so it is verified
against a real running server and a real MCP client — not mocked.
"""
from __future__ import annotations

import threading
import time

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from coderag_mcp.api.main import app

TEST_PORT = 8765


@pytest.fixture()
def live_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn server did not start in time"

    yield f"http://127.0.0.1:{TEST_PORT}/mcp"

    server.should_exit = True
    thread.join(timeout=5)


async def test_ping_tool_over_streamable_http(live_server):
    async with streamablehttp_client(live_server) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("ping", {})
            assert result.content[0].text == "pong"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_mcp_server.py -v`
Expected: FAIL — `ModuleNotFoundError` for `coderag_mcp.mcp_server`, since that package doesn't exist yet.

- [x] **Step 3: Write `coderag_mcp/mcp_server/__init__.py`**

```python
"""MCP server package: exposes CodeRAG-MCP's tools over Streamable HTTP."""
```

- [x] **Step 4: Write `coderag_mcp/mcp_server/server.py`**

```python
"""MCP server exposing CodeRAG-MCP's tools.

This starts with one dummy tool to validate the Streamable HTTP protocol
integration end-to-end before the real indexing/search/ask tools are built
on top of it in a later plan.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("coderag-mcp")


@mcp.tool()
def ping() -> str:
    """Trivial health-check tool: returns "pong"."""
    return "pong"
```

- [x] **Step 5: Rewrite `coderag_mcp/api/main.py` to mount the MCP app**

Replace the full file contents with:

```python
"""FastAPI application entrypoint, with the MCP server mounted at /mcp."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from coderag_mcp.mcp_server.server import mcp

mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_app.lifespan(mcp_app):
        yield


app = FastAPI(title="CodeRAG-MCP", lifespan=lifespan)
app.mount("/mcp", mcp_app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

If the installed `mcp` SDK's `streamable_http_app()`/lifespan API differs from this (see the "Important" note above the steps), adapt this file to the real API while keeping: (a) `app` as the FastAPI instance importable from `coderag_mcp.api.main`, (b) the MCP server mounted at `/mcp`, (c) the `/health` endpoint from Task 1 still working.

- [x] **Step 6: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_mcp_server.py -v`
Expected: PASS (1 passed). If it fails with an API-mismatch error (not an assertion failure), that confirms the SDK's real API differs from Step 5's code — go back to Step 5 and adapt using the installed package's actual signatures, then re-run.

- [x] **Step 7: Run the full test suite to check for regressions**

Run: `./.venv/bin/pytest -v`
Expected: both `tests/test_health.py::test_health_returns_ok` and `tests/test_mcp_server.py::test_ping_tool_over_streamable_http` pass (2 passed). The `/health` endpoint must still work with the MCP app mounted alongside it.

- [x] **Step 8: Commit**

```bash
cd /Users/estanislaomolinas/proyecto-api-backend-agents/coderag-mcp
git add coderag_mcp tests
git commit -m "Add MCP server spike: ping tool over Streamable HTTP, verified end-to-end"
```
