import pytest
import sqlite3
from unittest.mock import patch, MagicMock

import apsw

from coderag_mcp.indexing.models import Chunk
from coderag_mcp.orchestrator.indexing_service import index_and_store_repo
from coderag_mcp.store import repos as repo_store
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


def test_no_repos_row_created_if_embed_batch_raises(tmp_path):
    """If embed_batch fails, repos row should not exist (no poisoned state)."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            side_effect=RuntimeError("Voyage API timeout"),
        ),
    ):
        with pytest.raises(RuntimeError, match="Voyage API timeout"):
            index_and_store_repo(conn, "https://github.com/a/b")

    # Assert no poisoned row created
    assert repo_store.get_repo_id_by_url(conn, "https://github.com/a/b") is None


def test_no_repos_row_created_if_insert_chunks_raises(tmp_path):
    """If insert_chunks fails, repos row should not exist (no poisoned state)."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.chunk_store.insert_chunks",
            side_effect=RuntimeError("Disk full"),
        ),
    ):
        with pytest.raises(RuntimeError, match="Disk full"):
            index_and_store_repo(conn, "https://github.com/a/b")

    # Assert no poisoned row created (transaction was rolled back)
    assert repo_store.get_repo_id_by_url(conn, "https://github.com/a/b") is None


def test_concurrent_calls_recover_with_real_constraint_error(tmp_path):
    """Test concurrent race with real apsw.ConstraintError (not mocked)."""
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)
    init_schema(conn, dim=4)

    # Simulate a concurrent call by manually creating the repo in a separate transaction
    # before index_and_store_repo tries to create it
    def mock_create_repo_concurrent(conn_arg, url):
        # The real store layer's create_repo will see the row already exists
        # and raise apsw.ConstraintError
        raise apsw.ConstraintError("UNIQUE constraint failed: repos.url")

    with (
        patch(
            "coderag_mcp.orchestrator.indexing_service.index_repo",
            return_value=[_chunk()],
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.embed_batch",
            return_value=[[1.0, 0.0, 0.0, 0.0]],
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.repo_store.create_repo",
            side_effect=mock_create_repo_concurrent,
        ),
        patch(
            "coderag_mcp.orchestrator.indexing_service.chunk_store.insert_chunks",
        ),
    ):
        # Mock get_repo_id_by_url to return the repo_id from the concurrent caller
        with patch(
            "coderag_mcp.orchestrator.indexing_service.repo_store.get_repo_id_by_url",
            side_effect=[None, 42],  # First call returns None, second (after exception) returns 42
        ):
            repo_id = index_and_store_repo(conn, "https://github.com/a/b")
            # Should return the repo_id from concurrent caller, not raise
            assert repo_id == 42
