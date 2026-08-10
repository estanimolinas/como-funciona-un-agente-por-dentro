"""Idempotent glue: index a repo (Plan 2 pipeline) and store its embedded chunks."""
from __future__ import annotations

import asyncio
import sqlite3

import apsw

from coderag_mcp.embeddings.voyage import embed_batch
from coderag_mcp.indexing.models import Chunk
from coderag_mcp.indexing.pipeline import index_repo
from coderag_mcp.store import chunks as chunk_store
from coderag_mcp.store import repos as repo_store
from coderag_mcp.store.db import run_db_sync, transaction


def _clone_chunk_and_embed(
    repo_url: str,
) -> tuple[list[Chunk], list[list[float]] | None]:
    """Non-DB work: clone, chunk, embed. Touches no shared connection, so this is
    safe (and, via async callers, expected) to run without db_lock held."""
    extracted = index_repo(repo_url, allow_local_paths=False)

    # Embed chunks if any exist (before creating repo, so embedding failures don't poison the DB)
    embeddings = None
    if extracted:
        embeddings = embed_batch([chunk.source for chunk in extracted])
    return extracted, embeddings


def _store_repo_and_chunks(
    conn: sqlite3.Connection,
    repo_url: str,
    extracted: list[Chunk],
    embeddings: list[list[float]] | None,
) -> int:
    """DB work only: create the repo row and insert its chunks, atomically. This is
    the only part of indexing that needs db_lock - callers should run it via
    run_db_sync."""
    with transaction(conn):
        try:
            repo_id = repo_store.create_repo(conn, repo_url)
        except apsw.ConstraintError:
            # Concurrent call created the row first - look up the winner's repo_id
            # instead. Only create_repo's ConstraintError is reinterpreted this way;
            # a ConstraintError from insert_chunks (below) is a real, unrelated
            # failure and must propagate normally via the `with transaction(conn):`
            # block's own exception handling (which rolls back and re-raises).
            repo_id = repo_store.get_repo_id_by_url(conn, repo_url)
            assert repo_id is not None
            return repo_id
        if extracted:
            chunk_store.insert_chunks(conn, repo_id, extracted, embeddings)

    return repo_id


def index_and_store_repo(conn: sqlite3.Connection, repo_url: str) -> int:
    """Return the repo's id, indexing and embedding it first if not already stored.

    Plain sync, all-in-one composition of the clone/chunk/embed and store steps -
    used directly by tests and anywhere else that already owns exclusive access to
    `conn` (no concurrency to worry about). Real async callers that share `conn`
    with other concurrent requests should use `index_and_store_repo_async` instead,
    which only holds db_lock for the store step.
    """
    existing_id = repo_store.get_repo_id_by_url(conn, repo_url)
    if existing_id is not None:
        return existing_id

    extracted, embeddings = _clone_chunk_and_embed(repo_url)
    return _store_repo_and_chunks(conn, repo_url, extracted, embeddings)


async def index_and_store_repo_async(conn: sqlite3.Connection, repo_url: str) -> int:
    """Async, lock-scoped equivalent of `index_and_store_repo` for real callers
    (api/ask_route.py, mcp_server/server.py) whose `conn` is shared with other
    concurrent requests across both the /ask and /mcp transports.

    Only the DB-touching steps (the existing-repo check and the final store) run
    under db_lock, via `run_db_sync`. Cloning (up to ~60s) and embedding (up to
    ~120s) run unlocked via `asyncio.to_thread`, since neither touches the shared
    connection - so a slow first-time index no longer blocks every other
    DB-touching call on both transports for its full duration, only for the brief
    final write.
    """
    existing_id = await run_db_sync(repo_store.get_repo_id_by_url, conn, repo_url)
    if existing_id is not None:
        return existing_id

    extracted, embeddings = await asyncio.to_thread(_clone_chunk_and_embed, repo_url)

    return await run_db_sync(_store_repo_and_chunks, conn, repo_url, extracted, embeddings)
