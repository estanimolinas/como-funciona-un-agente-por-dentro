"""Tests for coderag_mcp.indexing.clone.clone_repo."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coderag_mcp.indexing import clone as clone_module
from coderag_mcp.indexing.clone import clone_repo
from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError, RepoTooLargeError


def test_rejects_disallowed_host():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("https://evil.example.com/repo.git")


def test_rejects_bare_ip():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("https://127.0.0.1/repo.git")


def test_rejects_localhost():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("https://localhost/repo.git")


def test_clones_local_fixture_repo(fixture_repo: Path):
    cloned_path = clone_repo(str(fixture_repo), allow_local_paths=True)
    try:
        assert cloned_path.is_dir()
        assert (cloned_path / "functions.py").exists()
        assert (cloned_path / "classes.py").exists()
    finally:
        import shutil

        shutil.rmtree(cloned_path.parent, ignore_errors=True)


def test_enforces_size_cap(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    from coderag_mcp.config import Settings

    monkeypatch.setattr(
        clone_module, "get_settings", lambda: Settings(max_repo_size_mb=0)
    )
    with pytest.raises(RepoTooLargeError):
        clone_repo(str(fixture_repo), allow_local_paths=True)


def test_enforces_clone_timeout(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git clone", timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(clone_module.subprocess, "run", _fake_run)
    with pytest.raises(CloneTimeoutError):
        clone_repo(str(fixture_repo), allow_local_paths=True)


def test_rejects_local_path_without_opt_in(fixture_repo: Path):
    with pytest.raises(InvalidRepoURLError):
        clone_repo(str(fixture_repo))


def test_rejects_dash_prefixed_url():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("--upload-pack=touch /tmp/pwned")


def test_rejects_scp_style_ssh_url():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("git@evil-host.example:attacker/repo.git")


def test_rejects_file_scheme():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("file:///etc/passwd")


def test_rejects_userless_scp_style_url():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("10.0.0.5:repo.git")


def test_rejects_userless_scp_style_url_with_metadata_ip():
    with pytest.raises(InvalidRepoURLError):
        clone_repo("169.254.169.254:repo.git")
