"""Data model and exception hierarchy for the indexing pipeline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    """A single AST-aware unit of code extracted from a repo file."""

    repo_url: str
    file_path: str
    symbol_type: str  # "function" | "class" | "method"
    symbol_name: str
    start_line: int
    end_line: int
    signature: str
    source: str
    parent_class: str | None = None


class IndexingError(Exception):
    """Base class for job-level indexing pipeline failures."""


class InvalidRepoURLError(IndexingError):
    """The repo URL's host is not on the allowlist, or the URL is malformed."""


class CloneTimeoutError(IndexingError):
    """`git clone` did not finish within the allotted time."""


class RepoTooLargeError(IndexingError):
    """The cloned repo's working tree exceeds the size cap."""


class TooManyFilesError(IndexingError):
    """The repo has more `.py` files than the pipeline will parse."""


class PipelineTimeoutError(IndexingError):
    """Clone + parse together exceeded the pipeline's wall-clock budget."""
