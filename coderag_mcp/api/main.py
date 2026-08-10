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
from coderag_mcp.api.auth import ApiKeyMiddleware
from coderag_mcp.config import get_settings, validate_settings
from coderag_mcp.logging_config import configure_logging
from coderag_mcp.mcp_server.server import mcp
from coderag_mcp.store.db import get_connection, init_schema


def create_app() -> FastAPI:
    """Build a fresh FastAPI app instance.

    Factored out (rather than only building a module-level singleton) because
    the `mcp` SDK's `StreamableHTTPSessionManager` can only be `.run()` once
    per instance — a fresh call to `mcp.streamable_http_app()` is required to
    get a fresh session manager. Production code only ever calls this once
    (see `app = create_app()` below); tests that need to spin up a second,
    independent live server (e.g. to exercise `/mcp` auth in isolation from
    the module-level `app`) can call `create_app()` again.

    `settings = get_settings()` is read fresh here (not at module scope) so that
    a monkeypatched `get_settings` is picked up by every `create_app()` call,
    same as `mcp_server/server.py`'s `_lifespan` already does - `get_settings()`
    is `@lru_cache`d, so this doesn't add repeated file I/O.
    """
    configure_logging()
    settings = get_settings()
    validate_settings(settings)

    # mcp.streamable_http_app() mutates the shared, module-level `mcp` object's
    # internal `_session_manager` attribute as a side effect (per the installed
    # SDK's mcp/server/lowlevel/server.py). Harmless here: both this function's
    # routing (via `mcp_app`) and its lifespan (via `mcp_app.router.lifespan_context`
    # below) close over this call's local `mcp_app`/session-manager reference, not
    # the mutated shared attribute on `mcp` - so calling create_app() again (as
    # tests do) can't cross-contaminate an earlier app instance.
    mcp_app = mcp.streamable_http_app(streamable_http_path="/", host=settings.public_host)
    mcp_app.add_middleware(ApiKeyMiddleware)

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

    return app


app = create_app()
