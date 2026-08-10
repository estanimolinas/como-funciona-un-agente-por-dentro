import sqlite3

import pytest

from coderag_mcp.store.db import get_connection, init_schema


@pytest.mark.asyncio
async def test_run_db_sync_offloads_to_a_thread_and_returns_the_result():
    import threading

    from coderag_mcp.store.db import run_db_sync

    caller_thread = threading.current_thread()
    seen_thread = {}

    def _work(x, y):
        seen_thread["thread"] = threading.current_thread()
        return x + y

    result = await run_db_sync(_work, 2, 3)

    assert result == 5
    assert seen_thread["thread"] is not caller_thread


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


def test_executescript_handles_semicolons_in_string_literals(tmp_path):
    """Test that executescript correctly handles semicolons inside string literals.

    This is a regression test for naive sql.split(";") which would incorrectly
    split on semicolons inside string literals, causing syntax errors.
    """
    conn = get_connection(str(tmp_path / "test.db"))

    # Schema with a DEFAULT containing a semicolon inside a string literal
    sql = """
    CREATE TABLE IF NOT EXISTS test_table (
        id INTEGER PRIMARY KEY,
        data TEXT DEFAULT 'value;with;semicolons'
    );
    """
    conn.executescript(sql)

    # Verify the table was created with the correct DEFAULT value
    result = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='test_table'"
    ).fetchone()
    assert result is not None
    assert "value;with;semicolons" in result[0]

    # Verify we can insert a row and the default is applied
    conn.execute("INSERT INTO test_table (id) VALUES (1)")
    conn.commit()
    row = conn.execute("SELECT data FROM test_table WHERE id=1").fetchone()
    assert row[0] == "value;with;semicolons"


def test_transaction_commits_on_success(tmp_path):
    from coderag_mcp.store.db import get_connection, init_schema, transaction

    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)

    with transaction(conn):
        conn.execute("INSERT INTO repos (url) VALUES (?)", ("https://github.com/a/b",))

    row = conn.execute("SELECT url FROM repos").fetchone()
    assert row[0] == "https://github.com/a/b"


def test_transaction_rolls_back_on_exception(tmp_path):
    from coderag_mcp.store.db import get_connection, init_schema, transaction

    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)

    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO repos (url) VALUES (?)", ("https://github.com/a/b",))
            raise RuntimeError("boom")

    row = conn.execute("SELECT COUNT(*) FROM repos").fetchone()
    assert row[0] == 0


def test_transaction_nested_call_does_not_commit_or_rollback_early(tmp_path):
    """A transaction() opened while one is already active must not touch it -
    only the outermost transaction() call owns commit/rollback."""
    from coderag_mcp.store.db import get_connection, init_schema, transaction

    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)

    with transaction(conn):
        with transaction(conn):
            conn.execute("INSERT INTO repos (url) VALUES (?)", ("https://github.com/a/b",))
        # Inner transaction() exited without committing - row must still be
        # visible on this same connection (uncommitted writes are visible to
        # the same connection) but only the outer exit actually commits.
        assert conn.in_transaction is True

    assert conn.in_transaction is False
    row = conn.execute("SELECT COUNT(*) FROM repos").fetchone()
    assert row[0] == 1
