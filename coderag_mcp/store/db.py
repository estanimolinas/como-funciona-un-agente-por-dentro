"""SQLite connection and schema management, with the sqlite-vec extension loaded."""
from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, Iterator, TypeVar

import apsw

EMBEDDING_DIM = 1024  # voyage-code-3 output dimension

db_lock = asyncio.Lock()

_T = TypeVar("_T")


async def run_db_sync(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Run a blocking, DB-touching callable off the event loop, serialized by db_lock.

    apsw connections aren't safe for concurrent use from multiple threads at once;
    asyncio.to_thread alone would let several ThreadPoolExecutor workers touch the
    same shared connection simultaneously. db_lock is acquired here (on the event
    loop, before the thread is spawned) so only one such call runs at a time.
    """
    async with db_lock:
        return await asyncio.to_thread(fn, *args, **kwargs)


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
        """Execute multiple SQL statements.

        Uses apsw's native multi-statement execution which correctly
        handles semicolons inside string literals and other SQL constructs.
        """
        cursor = self._conn.cursor()
        # apsw's cursor.execute() correctly handles multiple semicolon-separated
        # statements, including proper handling of semicolons in string literals
        list(cursor.execute(sql))

    def commit(self) -> None:
        """Commit the current transaction if one is active.

        In apsw, statements are autocommitted by default. This method only
        issues a COMMIT if a transaction is currently active (i.e., after BEGIN).
        """
        if self._conn.in_transaction:
            cursor = self._conn.cursor()
            list(cursor.execute("COMMIT"))

    def begin(self) -> None:
        """Begin a new transaction."""
        cursor = self._conn.cursor()
        list(cursor.execute("BEGIN"))

    def rollback(self) -> None:
        """Rollback the current transaction if one is active."""
        if self._conn.in_transaction:
            cursor = self._conn.cursor()
            list(cursor.execute("ROLLBACK"))

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    @property
    def in_transaction(self) -> bool:
        """True if a transaction is currently active on this connection."""
        return self._conn.in_transaction


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
        return self._conn.last_insert_rowid()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a block atomically, committing on success and rolling back on exception.

    If a transaction is already active on ``conn`` (e.g. this is a nested call from
    a caller that already opened one), this is a no-op wrapper: it neither begins nor
    commits/rolls back - only the outermost ``transaction()`` call for a given
    connection owns the transaction's lifecycle. This lets store-layer functions
    (``create_repo``, ``insert_chunks``) be called either standalone or as part of a
    larger caller-managed transaction (``index_and_store_repo``) without duplicating
    "am I the owner?" logic at each call site.
    """
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.begin()
    try:
        yield
        if owns_transaction:
            conn.commit()
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise


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
