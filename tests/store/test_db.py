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
