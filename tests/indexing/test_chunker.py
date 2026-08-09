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


def test_non_utf8_file_returns_no_chunks_without_raising(tmp_path: Path):
    py_file = tmp_path / "bad_encoding.py"
    py_file.write_bytes(b"def f():\n    x = '\xe9'\n    return x\n")

    chunks = chunk_file(py_file, REPO_URL, "bad_encoding.py")
    assert chunks == []


def test_extracts_decorated_function_and_method(tmp_path: Path):
    source = '''\
import functools
from dataclasses import dataclass


@functools.lru_cache
def cached_add(a: int, b: int) -> int:
    """Add two numbers, cached."""
    return a + b


@functools.wraps(cached_add)
@functools.lru_cache
def double_decorated(a: int) -> int:
    """Has two stacked decorators."""
    return a * 2


@dataclass
class Point:
    """A simple point."""

    x: int
    y: int


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
    assert names == {"cached_add", "double_decorated", "Point", "Widget", "make", "label"}

    cached_add_chunk = next(c for c in chunks if c.symbol_name == "cached_add")
    assert cached_add_chunk.symbol_type == "function"
    assert cached_add_chunk.signature == "def cached_add(a: int, b: int) -> int:"
    assert "@functools.lru_cache" in cached_add_chunk.source

    double_decorated_chunk = next(c for c in chunks if c.symbol_name == "double_decorated")
    assert double_decorated_chunk.symbol_type == "function"
    assert "@functools.wraps(cached_add)" in double_decorated_chunk.source
    assert "@functools.lru_cache" in double_decorated_chunk.source

    point_chunk = next(c for c in chunks if c.symbol_name == "Point")
    assert point_chunk.symbol_type == "class"
    assert point_chunk.signature == "class Point:"
    # Class chunks' start_line covers the decorator line (line numbers come
    # from the outer decorated_definition node), even though the class
    # chunk's `source` text itself is built from the class body only and
    # does not repeat the decorator line — unlike function/method chunks,
    # which do include their decorator(s) in `source`.
    assert "@dataclass" not in point_chunk.source

    make_chunk = next(c for c in chunks if c.symbol_name == "make")
    assert make_chunk.symbol_type == "method"
    assert make_chunk.parent_class == "Widget"
    assert "@staticmethod" in make_chunk.source

    label_chunk = next(c for c in chunks if c.symbol_name == "label")
    assert label_chunk.parent_class == "Widget"
    assert "@property" in label_chunk.source
