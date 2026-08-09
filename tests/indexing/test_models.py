"""Tests for the Chunk dataclass and indexing exception hierarchy."""
from __future__ import annotations

import pytest

from coderag_mcp.indexing.models import (
    Chunk,
    CloneTimeoutError,
    IndexingError,
    InvalidRepoURLError,
    PipelineTimeoutError,
    RepoTooLargeError,
    TooManyFilesError,
)


def test_chunk_holds_expected_fields():
    chunk = Chunk(
        repo_url="https://github.com/example/repo",
        file_path="pkg/mod.py",
        symbol_type="function",
        symbol_name="add",
        start_line=1,
        end_line=3,
        signature="def add(a: int, b: int) -> int:",
        source="def add(a: int, b: int) -> int:\n    return a + b\n",
    )
    assert chunk.parent_class is None
    assert chunk.symbol_type == "function"
    assert chunk.start_line == 1
    assert chunk.end_line == 3


@pytest.mark.parametrize(
    "exc_type",
    [
        InvalidRepoURLError,
        CloneTimeoutError,
        RepoTooLargeError,
        TooManyFilesError,
        PipelineTimeoutError,
    ],
)
def test_job_level_exceptions_subclass_indexing_error(exc_type):
    assert issubclass(exc_type, IndexingError)
    assert issubclass(IndexingError, Exception)
