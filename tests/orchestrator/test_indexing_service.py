from unittest.mock import patch

from coderag_mcp.indexing.models import Chunk
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.store.chunks import search_chunks
from coderag_mcp.store.db import get_connection, init_schema


def _chunk() -> Chunk:
    return Chunk(
        repo_url="https://github.com/a/b",
        file_path="mod.py",
        symbol_type="function",
        symbol_name="f",
        start_line=1,
        end_line=2,
        signature="def f():",
        source="def f():\n    pass",
    )


def test_indexes_and_stores_on_first_call(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ) as mock_index,
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
    ):
        repo_id = index_and_store_repo(conn, "https://github.com/a/b")

    mock_index.assert_called_once_with(
        "https://github.com/a/b", allow_local_paths=False
    )
    results = search_chunks(conn, repo_id, [1.0, 0.0, 0.0, 0.0], top_k=1)
    assert results[0].symbol_name == "f"


def test_second_call_reuses_existing_repo_without_reindexing(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ) as mock_index,
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
    ):
        first_id = index_and_store_repo(conn, "https://github.com/a/b")
        second_id = index_and_store_repo(conn, "https://github.com/a/b")

    assert first_id == second_id
    mock_index.assert_called_once()
