"""FastAPI dependencies shared across routes."""
from __future__ import annotations

import sqlite3

from fastapi import Request


def get_db_conn(request: Request) -> sqlite3.Connection:
    """The shared SQLite connection opened once at app startup (see api/main.py's
    lifespan) - never call store.db.get_connection() per-request in a route."""
    return request.app.state.db_conn
