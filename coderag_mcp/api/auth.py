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
