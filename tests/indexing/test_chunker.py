"""Tests for coderag_mcp.indexing.chunker.chunk_file."""
from __future__ import annotations

from pathlib import Path

from coderag_mcp.indexing.chunker import chunk_file

REPO_URL = "https://github.com/example/repo"


def test_extracts_top_level_function(fixture_repo: Path):
    chunks = chunk_file(fixture_repo / "functions.py", REPO_URL, "functions.py")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.symbol_type == "function"
    assert chunk.symbol_name == "add"
    assert chunk.parent_class is None
    assert chunk.repo_url == REPO_URL
    assert chunk.file_path == "functions.py"
    assert chunk.signature == "def add(a: int, b: int) -> int:"
    assert "return a + b" in chunk.source
    assert chunk.start_line == 1
    assert chunk.end_line == 3


def test_extracts_class_and_its_methods(fixture_repo: Path):
    chunks = chunk_file(fixture_repo / "classes.py", REPO_URL, "classes.py")

    class_chunks = [c for c in chunks if c.symbol_type == "class"]
    method_chunks = [c for c in chunks if c.symbol_type == "method"]

    assert len(class_chunks) == 1
    assert class_chunks[0].symbol_name == "Greeter"
    assert class_chunks[0].parent_class is None
    assert "Greets people by name" in class_chunks[0].source

    assert len(method_chunks) == 2
    method_names = {c.symbol_name for c in method_chunks}
    assert method_names == {"__init__", "greet"}
    for method_chunk in method_chunks:
        assert method_chunk.parent_class == "Greeter"


def test_broken_syntax_file_returns_no_chunks_without_raising(fixture_repo: Path):
    chunks = chunk_file(fixture_repo / "broken.py", REPO_URL, "broken.py")
    assert chunks == []


def test_extracts_decorated_function_and_method(tmp_path: Path):
    source = '''\
import functools


@functools.lru_cache
def cached_add(a: int, b: int) -> int:
    """Add two numbers, cached."""
    return a + b


class Widget:
    """A widget."""

    @staticmethod
    def make() -> "Widget":
        """Factory method."""
        return Widget()

    @property
    def label(self) -> str:
        """Return the widget's label."""
        return "widget"
'''
    py_file = tmp_path / "decorated.py"
    py_file.write_text(source)

    chunks = chunk_file(py_file, REPO_URL, "decorated.py")

    names = {c.symbol_name for c in chunks}
    assert names == {"cached_add", "Widget", "make", "label"}

    cached_add_chunk = next(c for c in chunks if c.symbol_name == "cached_add")
    assert cached_add_chunk.symbol_type == "function"
    assert cached_add_chunk.signature == "def cached_add(a: int, b: int) -> int:"
    assert "@functools.lru_cache" in cached_add_chunk.source

    make_chunk = next(c for c in chunks if c.symbol_name == "make")
    assert make_chunk.symbol_type == "method"
    assert make_chunk.parent_class == "Widget"
    assert "@staticmethod" in make_chunk.source

    label_chunk = next(c for c in chunks if c.symbol_name == "label")
    assert label_chunk.parent_class == "Widget"
    assert "@property" in label_chunk.source
