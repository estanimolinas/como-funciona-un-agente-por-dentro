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
