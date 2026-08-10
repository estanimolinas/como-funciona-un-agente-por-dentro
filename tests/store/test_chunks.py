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
