"""Repo row lookups/creation, keyed by URL."""
from __future__ import annotations

import sqlite3


def get_repo_id_by_url(conn: sqlite3.Connection, url: str) -> int | None:
    row = conn.execute("SELECT id FROM repos WHERE url = ?", (url,)).fetchone()
    return row[0] if row else None


def create_repo(conn: sqlite3.Connection, url: str) -> int:
    # If a transaction is already active (e.g., called from a larger operation),
    # only manage (commit/rollback) the transaction if we started it - mirrors
    # store/chunks.py's insert_chunks, which shares this same ownership pattern.
    should_manage_transaction = not conn._conn.in_transaction
    try:
        cursor = conn.execute("INSERT INTO repos (url) VALUES (?)", (url,))
        if should_manage_transaction:
            conn.commit()
    except Exception:
        if should_manage_transaction:
            conn.rollback()
        raise
    assert cursor.lastrowid is not None
    return cursor.lastrowid
