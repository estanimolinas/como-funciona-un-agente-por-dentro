import sqlite3

from coderag_mcp.store.db import get_connection, init_schema


def test_init_schema_creates_tables(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
        )
    }
    assert {"repos", "chunks", "chunk_vectors"} <= tables


def test_init_schema_is_idempotent(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    init_schema(conn, dim=4)  # must not raise
