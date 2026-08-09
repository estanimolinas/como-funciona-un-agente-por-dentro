"""Tests for coderag_mcp.indexing.pipeline.index_repo."""
from __future__ import annotations

from pathlib import Path

import pytest

from coderag_mcp.indexing import pipeline as pipeline_module
from coderag_mcp.indexing.models import PipelineTimeoutError, TooManyFilesError
from coderag_mcp.indexing.pipeline import index_repo


def test_index_repo_returns_expected_chunks(fixture_repo: Path):
    chunks = index_repo(str(fixture_repo), allow_local_paths=True)

    symbol_names = {c.symbol_name for c in chunks}
    assert symbol_names == {"add", "Greeter", "__init__", "greet"}

    function_chunk = next(c for c in chunks if c.symbol_name == "add")
    assert function_chunk.repo_url == str(fixture_repo)
    assert function_chunk.file_path == "functions.py"

    # broken.py contributes no chunks, but does not abort the job
    assert all(c.file_path != "broken.py" for c in chunks)


def test_index_repo_cleans_up_temp_dir(fixture_repo: Path):
    chunks = index_repo(str(fixture_repo), allow_local_paths=True)
    assert chunks  # sanity: got real chunks
    # Every chunk's file_path is relative, so nothing here references the
    # temp dir directly; instead verify no coderag-clone-* dirs are left in
    # the system temp root after a successful run.
    import glob
    import tempfile

    leftovers = glob.glob(str(Path(tempfile.gettempdir()) / "coderag-clone-*"))
    assert leftovers == []


def test_index_repo_enforces_file_count_cap(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline_module, "MAX_FILE_COUNT", 1)
    with pytest.raises(TooManyFilesError):
        index_repo(str(fixture_repo), allow_local_paths=True)


def test_index_repo_enforces_pipeline_timeout(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline_module, "PIPELINE_TIMEOUT_S", -1)
    with pytest.raises(PipelineTimeoutError):
        index_repo(str(fixture_repo), allow_local_paths=True)
