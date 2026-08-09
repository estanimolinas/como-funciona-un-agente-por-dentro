"""Orchestrates clone -> discover .py files -> chunk into the pipeline's public entry point."""
from __future__ import annotations

import logging
import time

from coderag_mcp.indexing import clone
from coderag_mcp.indexing.chunker import chunk_file
from coderag_mcp.indexing.clone import clone_repo
from coderag_mcp.indexing.models import Chunk, PipelineTimeoutError, TooManyFilesError

logger = logging.getLogger(__name__)

MAX_FILE_COUNT = 500
PIPELINE_TIMEOUT_S = 120


def index_repo(repo_url: str, *, allow_local_paths: bool = False) -> list[Chunk]:
    """Clone, parse, and chunk a repo. Raises IndexingError subclasses on job-level failure."""
    start = time.monotonic()
    repo_dir = clone_repo(repo_url, allow_local_paths=allow_local_paths)

    try:
        py_files = sorted(repo_dir.rglob("*.py"))
        if len(py_files) > MAX_FILE_COUNT:
            raise TooManyFilesError(
                f"{repo_url!r} has {len(py_files)} .py files, exceeds {MAX_FILE_COUNT} cap"
            )

        chunks: list[Chunk] = []
        for py_file in py_files:
            if time.monotonic() - start > PIPELINE_TIMEOUT_S:
                raise PipelineTimeoutError(
                    f"indexing {repo_url!r} exceeded {PIPELINE_TIMEOUT_S}s"
                )
            file_path = str(py_file.relative_to(repo_dir))
            try:
                chunks.extend(chunk_file(py_file, repo_url, file_path))
            except Exception as exc:  # noqa: BLE001 - per-file failures must never abort the job
                logger.warning("chunk_file failed for %s: %s", file_path, exc)
        return chunks
    finally:
        clone.cleanup_clone(repo_dir)
