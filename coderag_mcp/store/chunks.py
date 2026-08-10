"""Chunk storage and cosine-similarity search over sqlite-vec."""
from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass

from coderag_mcp.indexing.models import Chunk


@dataclass
class ChunkResult:
    file_path: str
    symbol_type: str
    symbol_name: str
    start_line: int
    end_line: int
    signature: str
    source: str
    distance: float


def _serialize(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def insert_chunks(
    conn: sqlite3.Connection,
    repo_id: int,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must be the same length")

    for chunk, embedding in zip(chunks, embeddings):
        cursor = conn.execute(
            """
            INSERT INTO chunks
                (repo_id, file_path, symbol_type, symbol_name, start_line, end_line,
                 signature, source, parent_class)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo_id,
                chunk.file_path,
                chunk.symbol_type,
                chunk.symbol_name,
                chunk.start_line,
                chunk.end_line,
                chunk.signature,
                chunk.source,
                chunk.parent_class,
            ),
        )
        conn.execute(
            "INSERT INTO chunk_vectors (chunk_id, repo_id, embedding) VALUES (?, ?, ?)",
            (cursor.lastrowid, repo_id, _serialize(embedding)),
        )
    conn.commit()


def search_chunks(
    conn: sqlite3.Connection,
    repo_id: int,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[ChunkResult]:
    matches = conn.execute(
        """
        SELECT chunk_id, distance
        FROM chunk_vectors
        WHERE embedding MATCH ? AND k = ? AND repo_id = ?
        ORDER BY distance
        """,
        (_serialize(query_embedding), top_k, repo_id),
    ).fetchall()
    if not matches:
        return []

    distance_by_id = {chunk_id: distance for chunk_id, distance in matches}
    placeholders = ",".join("?" * len(distance_by_id))
    rows = conn.execute(
        f"""
        SELECT id, file_path, symbol_type, symbol_name, start_line, end_line,
               signature, source
        FROM chunks WHERE id IN ({placeholders})
        """,
        list(distance_by_id.keys()),
    ).fetchall()

    results = [
        ChunkResult(*row[1:], distance=distance_by_id[row[0]]) for row in rows
    ]
    results.sort(key=lambda r: r.distance)
    return results
