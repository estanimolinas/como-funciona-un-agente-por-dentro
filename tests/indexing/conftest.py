"""Shared fixtures for indexing pipeline tests: a real local git repo."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

FUNCTIONS_PY = '''\
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''

CLASSES_PY = '''\
class Greeter:
    """Greets people by name."""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        """Return a greeting for self.name."""
        return f"Hello, {self.name}"
'''

BROKEN_PY = '''\
def broken(
    this is not valid python syntax
'''


def _run_git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    """Create a real local git repo with known Python files for chunker/clone/pipeline tests."""
    repo_dir = tmp_path / "fixture_repo"
    repo_dir.mkdir()
    (repo_dir / "functions.py").write_text(FUNCTIONS_PY)
    (repo_dir / "classes.py").write_text(CLASSES_PY)
    (repo_dir / "broken.py").write_text(BROKEN_PY)

    _run_git("init", cwd=repo_dir)
    _run_git("config", "user.email", "test@example.com", cwd=repo_dir)
    _run_git("config", "user.name", "Test", cwd=repo_dir)
    _run_git("add", ".", cwd=repo_dir)
    _run_git("commit", "-m", "initial commit", cwd=repo_dir)

    return repo_dir
