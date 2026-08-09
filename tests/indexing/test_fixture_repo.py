"""Smoke test for the fixture_repo pytest fixture itself."""
from __future__ import annotations

import subprocess
from pathlib import Path


def test_fixture_repo_is_a_real_git_repo_with_expected_files(fixture_repo: Path):
    assert (fixture_repo / ".git").is_dir()
    assert (fixture_repo / "functions.py").exists()
    assert (fixture_repo / "classes.py").exists()
    assert (fixture_repo / "broken.py").exists()

    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=fixture_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "initial commit" in result.stdout
