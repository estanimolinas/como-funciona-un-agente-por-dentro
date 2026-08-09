"""tree-sitter-based extraction of function/class/method chunks from .py files."""
from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from coderag_mcp.indexing.models import Chunk

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode()


def _unwrap_decorated(node: Node) -> Node | None:
    """Return the function/class definition inside a decorated_definition node.

    If the node is not a decorated_definition, return it as-is.
    If it is a decorated_definition but has no matching child, return None.
    """
    if node.type != "decorated_definition":
        return node
    for child in node.named_children:
        if child.type in ("function_definition", "class_definition"):
            return child
    return None


def _function_chunk(
    outer_node: Node,
    def_node: Node,
    source: bytes,
    repo_url: str,
    file_path: str,
    parent_class: str | None,
) -> Chunk:
    """Create a Chunk for a function or method.

    outer_node: The original node (may be decorated_definition), used for
                line numbers and full source (including decorators).
    def_node: The actual function_definition node, used for name and signature.
    """
    name_node = def_node.child_by_field_name("name")
    assert name_node is not None
    def_source = _node_text(def_node, source)
    signature = def_source.split("\n", 1)[0].rstrip()
    full_source = _node_text(outer_node, source)

    return Chunk(
        repo_url=repo_url,
        file_path=file_path,
        symbol_type="method" if parent_class else "function",
        symbol_name=_node_text(name_node, source),
        start_line=outer_node.start_point[0] + 1,
        end_line=outer_node.end_point[0] + 1,
        signature=signature,
        source=full_source,
        parent_class=parent_class,
    )


def _class_chunk(
    outer_node: Node,
    def_node: Node,
    source: bytes,
    repo_url: str,
    file_path: str,
) -> Chunk:
    """Create a Chunk for a class.

    outer_node: The original node (may be decorated_definition), used for
                line numbers (so decorator lines are included).
    def_node: The actual class_definition node, used for name and content.
    """
    name_node = def_node.child_by_field_name("name")
    body_node = def_node.child_by_field_name("body")
    assert name_node is not None and body_node is not None

    header = source[def_node.start_byte : body_node.start_byte].decode().rstrip()
    docstring = ""
    if body_node.named_child_count > 0:
        first_stmt = body_node.named_children[0]
        if first_stmt.type == "expression_statement" and first_stmt.named_child_count > 0:
            expr = first_stmt.named_children[0]
            if expr.type == "string":
                docstring = "\n" + _node_text(first_stmt, source)

    return Chunk(
        repo_url=repo_url,
        file_path=file_path,
        symbol_type="class",
        symbol_name=_node_text(name_node, source),
        start_line=outer_node.start_point[0] + 1,
        end_line=outer_node.end_point[0] + 1,
        signature=header,
        source=header + docstring,
        parent_class=None,
    )


def chunk_file(path: Path, repo_url: str, file_path: str) -> list[Chunk]:
    """Parse one .py file and return its function/class/method chunks.

    Returns an empty list (with a logged warning) if the file has syntax
    errors — per-file failures never abort the overall indexing job.
    """
    source = path.read_bytes()
    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source)

    if tree.root_node.has_error:
        logger.warning("skipping %s: syntax errors during parse", file_path)
        return []

    chunks: list[Chunk] = []
    for raw_node in tree.root_node.named_children:
        node = _unwrap_decorated(raw_node)
        if node is None:
            continue
        if node.type == "function_definition":
            chunks.append(_function_chunk(raw_node, node, source, repo_url, file_path, None))
        elif node.type == "class_definition":
            chunks.append(_class_chunk(raw_node, node, source, repo_url, file_path))
            class_name = _node_text(node.child_by_field_name("name"), source)
            body_node = node.child_by_field_name("body")
            for raw_child in body_node.named_children:
                child = _unwrap_decorated(raw_child)
                if child is not None and child.type == "function_definition":
                    chunks.append(
                        _function_chunk(raw_child, child, source, repo_url, file_path, class_name)
                    )
    return chunks
