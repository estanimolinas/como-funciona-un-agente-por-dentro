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


def test_real_unique_constraint_raises_apsw_constraint_error(tmp_path):
    """Verify that the REAL driver raises apsw.ConstraintError on UNIQUE violation."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    # Call create_repo once with a URL (succeeds)
    repo_id_1 = repo_store.create_repo(conn, "https://github.com/test/repo")
    assert repo_id_1 is not None

    # Call create_repo again with the SAME URL (should raise real apsw.ConstraintError)
    with pytest.raises(apsw.ConstraintError):
        repo_store.create_repo(conn, "https://github.com/test/repo")


def test_concurrent_calls_recover_from_real_constraint_error(tmp_path):
    """Prove index_and_store_repo's OWN create_repo call hits a genuine
    apsw.ConstraintError and recovers, mirroring a real concurrent race:

    - Caller A (this test, unmocked) inserts the row first via the real,
      unmocked repo_store.create_repo -- simulating the winner of the race.
    - Caller B (index_and_store_repo, the code under test) checks
      get_repo_id_by_url first, as it always does. We simulate the exact
      race window by making ONLY that first lookup report "not found" (as
      it would for a real concurrent caller that checked a moment before
      the winner's insert landed) -- every other call in the function,
      including the real create_repo and the recovery lookup, is
      completely unmocked.

    This forces execution to actually reach index_and_store_repo's own
    create_repo call, which then collides for real with the row Caller A
    already inserted, raising a genuine apsw.ConstraintError that the
    `except apsw.ConstraintError:` block must catch and recover from.
    """
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)
    init_schema(conn, dim=4)

    url = "https://github.com/concurrent/repo"

    # Caller A: the real, unmocked winner of the race. Row genuinely exists now.
    winner_repo_id = repo_store.create_repo(conn, url)

    # Simulate Caller B's pre-insert lookup seeing nothing yet: fake out ONLY
    # the first call to get_repo_id_by_url (the early-idempotency check inside
    # index_and_store_repo). Every subsequent call -- including the recovery
    # lookup inside the except block -- goes through to the real function.
    real_get_repo_id_by_url = repo_store.get_repo_id_by_url
    calls = {"n": 0}

    def fake_get_repo_id_by_url(conn, repo_url):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_get_repo_id_by_url(conn, repo_url)

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
            "coderag_mcp.orchestrator.indexing_service.repo_store.get_repo_id_by_url",
            side_effect=fake_get_repo_id_by_url,
        ),
    ):
        # index_and_store_repo's early check is fooled into proceeding, so it
        # calls the REAL create_repo itself, which collides for real with the
        # row Caller A already inserted -> genuine apsw.ConstraintError ->
        # the except block must recover and return the winner's repo_id.
        repo_id = index_and_store_repo(conn, url)

    assert calls["n"] >= 2, "test never reached the recovery lookup"
    assert repo_id == winner_repo_id
