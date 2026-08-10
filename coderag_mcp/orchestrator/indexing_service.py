"""Idempotent glue: index a repo (Plan 2 pipeline) and store its embedded chunks."""
from __future__ import annotations

import sqlite3

import apsw

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.indexing.pipeline import index_repo
from coderag_mcp.store import chunks as chunk_store
from coderag_mcp.store import repos as repo_store
from coderag_mcp.store.db import transaction


def index_and_store_repo(conn: sqlite3.Connection, repo_url: str) -> int:
    """Return the repo's id, indexing and embedding it first if not already stored."""
    existing_id = repo_store.get_repo_id_by_url(conn, repo_url)
    if existing_id is not None:
        return existing_id

    extracted = index_repo(repo_url, allow_local_paths=False)

    # Embed chunks if any exist (before creating repo, so embedding failures don't poison the DB)
    embeddings = None
    if extracted:
        embeddings = embed_batch([chunk.source for chunk in extracted])

    try:
        with transaction(conn):
            repo_id = repo_store.create_repo(conn, repo_url)
            if extracted:
                chunk_store.insert_chunks(conn, repo_id, extracted, embeddings)
    except apsw.ConstraintError:
        # Concurrent call created the row first; transaction() already rolled back
        # this attempt - look up the winner's repo_id instead.
        repo_id = repo_store.get_repo_id_by_url(conn, repo_url)
        assert repo_id is not None
        return repo_id

    return repo_id
