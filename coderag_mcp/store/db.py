"""SQLite connection and schema management, with the sqlite-vec extension loaded."""
from __future__ import annotations

import sqlite3
from typing import Any

import apsw

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


class _APSWWrapper:
    """Wrapper around apsw.Connection to provide a sqlite3-compatible interface."""

    def __init__(self, apsw_conn: apsw.Connection) -> None:
        self._conn = apsw_conn

    def execute(self, sql: str, parameters: tuple = ()) -> "_CursorWrapper":
        cursor = self._conn.cursor()
        if parameters:
            cursor.execute(sql, parameters)
        else:
            cursor.execute(sql)
        return _CursorWrapper(cursor, self._conn)

    def executescript(self, sql: str) -> None:
        """Execute multiple SQL statements."""
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                self.execute(statement)

    def commit(self) -> None:
        """Commit the transaction (no-op for apsw)."""
        pass

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()


class _CursorWrapper:
    """Wrapper around apsw.Cursor to provide sqlite3-compatible interface."""

    def __init__(self, apsw_cursor: Any, apsw_conn: apsw.Connection) -> None:
        self._cursor = apsw_cursor
        self._rows = list(apsw_cursor)
        self._index = 0
        self._conn = apsw_conn

    def __iter__(self):
        """Return iterator."""
        self._index = 0
        return self

    def __next__(self):
        """Get next row."""
        if self._index >= len(self._rows):
            raise StopIteration
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchone(self) -> tuple | None:
        """Fetch the next row."""
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list[tuple]:
        """Fetch all remaining rows."""
        remaining = self._rows[self._index :]
        self._index = len(self._rows)
        return remaining

    @property
    def lastrowid(self) -> int | None:
        """Get the last inserted row ID."""
        try:
            result = list(self._conn.cursor().execute("SELECT last_insert_rowid()"))
            return result[0][0] if result else None
        except Exception:
            return None


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get a connection with sqlite-vec extension loaded."""
    conn = apsw.Connection(db_path)
    conn.enable_load_extension(True)

    # Load sqlite-vec extension
    import sqlite_vec

    vec_path = sqlite_vec.loadable_path()
    # If the path without extension doesn't exist, try with .dylib
    import os

    if not os.path.exists(vec_path) and os.path.exists(vec_path + ".dylib"):
        vec_path = vec_path + ".dylib"

    conn.load_extension(vec_path)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")

    return _APSWWrapper(conn)


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
