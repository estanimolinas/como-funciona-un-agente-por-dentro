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

from coderag_mcp.config import get_settings
from coderag_mcp.mcp_server.server import mcp

settings = get_settings()

mcp_app = mcp.streamable_http_app(streamable_http_path="/", host=settings.public_host)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="CodeRAG-MCP", lifespan=lifespan)
app.mount("/mcp", mcp_app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
