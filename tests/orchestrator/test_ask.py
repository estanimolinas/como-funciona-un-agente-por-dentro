from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock

from coderag_mcp.orchestrator.ask import ask


async def _fake_query_stream(*, prompt, options):
    assert prompt == "how does auth work?"
    assert options.allowed_tools == ["mcp__search__search_code", "Read", "Grep", "Glob"]
    assert options.agents is None
    # A non-AssistantMessage should be ignored, not concatenated into the answer.
    yield SystemMessage(subtype="subagent_start", data={})
    yield AssistantMessage(content=[TextBlock(text="Auth is handled in ")], model="test")
    yield AssistantMessage(content=[TextBlock(text="auth.py:10-20.")], model="test")


@pytest.mark.asyncio
async def test_ask_concatenates_streamed_text_and_scopes_cwd(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path) as mock_clone,
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone") as mock_cleanup,
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_fake_query_stream),
    ):
        answer = await ask(conn, repo_id=1, repo_url="https://github.com/a/b", question="how does auth work?")

    assert answer == "Auth is handled in auth.py:10-20."
    mock_clone.assert_called_once_with("https://github.com/a/b", allow_local_paths=False)
    mock_cleanup.assert_called_once_with(tmp_path)
