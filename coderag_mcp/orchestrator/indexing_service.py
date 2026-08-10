"""Idempotent glue: index a repo (Plan 2 pipeline) and store its embedded chunks."""
from __future__ import annotations

import sqlite3

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.indexing.pipeline import index_repo
from coderag_mcp.store import chunks as chunk_store
from coderag_mcp.store import repos as repo_store


def index_and_store_repo(conn: sqlite3.Connection, repo_url: str) -> int:
    """Return the repo's id, indexing and embedding it first if not already stored."""
    existing_id = repo_store.get_repo_id_by_url(conn, repo_url)
    if existing_id is not None:
        return existing_id

    extracted = index_repo(repo_url, allow_local_paths=False)
    repo_id = repo_store.create_repo(conn, repo_url)

    if extracted:
        embeddings = embed_batch([chunk.source for chunk in extracted])
        chunk_store.insert_chunks(conn, repo_id, extracted, embeddings)

    return repo_id
