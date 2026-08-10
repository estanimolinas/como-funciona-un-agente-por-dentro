from coderag_mcp.indexing.models import Chunk
from coderag_mcp.store.chunks import insert_chunks, search_chunks
from coderag_mcp.store.db import get_connection, init_schema
from coderag_mcp.store.repos import create_repo


def _chunk(name: str) -> Chunk:
    return Chunk(
        repo_url="https://github.com/a/b",
        file_path="mod.py",
        symbol_type="function",
        symbol_name=name,
        start_line=1,
        end_line=2,
        signature=f"def {name}():",
        source=f"def {name}():\n    pass",
    )


def test_search_chunks_ranks_by_similarity(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    repo_id = create_repo(conn, "https://github.com/a/b")

    chunks = [_chunk("near"), _chunk("far")]
    embeddings = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    insert_chunks(conn, repo_id, chunks, embeddings)

    results = search_chunks(conn, repo_id, [1.0, 0.0, 0.0, 0.0], top_k=2)

    assert [r.symbol_name for r in results] == ["near", "far"]


def test_search_chunks_scoped_to_repo(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    repo_a = create_repo(conn, "https://github.com/a/a")
    repo_b = create_repo(conn, "https://github.com/b/b")

    insert_chunks(conn, repo_a, [_chunk("only_in_a")], [[1.0, 0.0, 0.0, 0.0]])
    insert_chunks(conn, repo_b, [_chunk("only_in_b")], [[1.0, 0.0, 0.0, 0.0]])

    results = search_chunks(conn, repo_a, [1.0, 0.0, 0.0, 0.0], top_k=5)

    assert [r.symbol_name for r in results] == ["only_in_a"]


def test_insert_chunks_rolls_back_on_failure(tmp_path):
    """Test that insert_chunks rolls back all changes if it fails mid-loop.

    Regression test for transaction handling: if a failure occurs partway
    through inserting multiple chunks (e.g., mismatched embedding dimensions),
    all chunks for that call should be rolled back, not just the failed one.
    This preserves idempotency: a failed insert attempt leaves the DB unchanged.
    """
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)
    repo_id = create_repo(conn, "https://github.com/a/b")

    # Try to insert 2 chunks where the 2nd has a mismatched embedding dimension
    chunks = [_chunk("first"), _chunk("second")]
    # Second embedding has wrong dimension (3 instead of 4)
    embeddings = [[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]

    # This should fail when trying to insert the second chunk's embedding
    try:
        insert_chunks(conn, repo_id, chunks, embeddings)
        assert False, "Expected insert_chunks to raise due to embedding mismatch"
    except Exception:
        pass  # Expected

    # Verify NO chunks were inserted (full rollback, not partial)
    result = conn.execute("SELECT COUNT(*) FROM chunks WHERE repo_id = ?", (repo_id,)).fetchone()
    assert result[0] == 0, "Expected 0 chunks after failed insert (full rollback)"

    # Verify we can now insert the same chunks with correct embeddings successfully
    embeddings_correct = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    insert_chunks(conn, repo_id, chunks, embeddings_correct)

    # Verify both chunks are now in the DB
    result = conn.execute("SELECT COUNT(*) FROM chunks WHERE repo_id = ?", (repo_id,)).fetchone()
    assert result[0] == 2, "Expected 2 chunks after successful insert"
