from coderag_mcp.orchestrator.agents import CODE_EXPLORER, RAG_SEARCH, fresh_clone


def test_code_explorer_tools_exclude_bash_and_write():
    assert CODE_EXPLORER.tools == ["Read", "Grep", "Glob"]
    assert "Bash" not in CODE_EXPLORER.tools
    assert "Write" not in CODE_EXPLORER.tools
    assert "Edit" not in CODE_EXPLORER.tools


def test_rag_search_uses_search_code_tool_only():
    assert RAG_SEARCH.tools == ["mcp__search__search_code"]


def test_fresh_clone_yields_and_cleans_up_repo_dir(tmp_path):
    import subprocess

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=source_repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=source_repo, check=True, capture_output=True
    )
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "x"], cwd=source_repo, check=True, capture_output=True
    )

    from coderag_mcp.indexing import clone as clone_module

    # fresh_clone always passes allow_local_paths=False; to test the context-manager
    # contract without network access, monkeypatch clone_repo/cleanup_clone directly.
    calls = []

    def fake_clone_repo(url, *, allow_local_paths=False):
        calls.append(("clone", url, allow_local_paths))
        return source_repo

    def fake_cleanup(path):
        calls.append(("cleanup", path))

    orig_clone, orig_cleanup = clone_module.clone_repo, clone_module.cleanup_clone
    clone_module.clone_repo = fake_clone_repo
    clone_module.cleanup_clone = fake_cleanup
    try:
        with fresh_clone("https://github.com/a/b") as repo_dir:
            assert repo_dir == source_repo
            assert calls == [("clone", "https://github.com/a/b", False)]
        assert calls[-1] == ("cleanup", source_repo)
    finally:
        clone_module.clone_repo = orig_clone
        clone_module.cleanup_clone = orig_cleanup
