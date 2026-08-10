from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock

from coderag_mcp.orchestrator.ask import ask


async def _fake_query_stream(*, prompt, options):
    assert prompt == "how does auth work?"
    assert options.agents.keys() == {"rag-search", "code-explorer"}
    assert "Agent" in options.allowed_tools
    # A non-AssistantMessage (e.g. a subagent-start SystemMessage) should be ignored,
    # not concatenated into the answer.
    yield SystemMessage(subtype="subagent_start", data={})
    yield AssistantMessage(content=[TextBlock(text="Auth is handled in ")], model="test")
    yield AssistantMessage(content=[TextBlock(text="auth.py:10-20.")], model="test")


@pytest.mark.asyncio
async def test_ask_concatenates_streamed_text_and_scopes_cwd(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.fresh_clone") as mock_fresh_clone,
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_fake_query_stream),
    ):
        mock_fresh_clone.return_value.__enter__.return_value = tmp_path
        mock_fresh_clone.return_value.__exit__.return_value = False

        answer = await ask(conn, repo_id=1, repo_url="https://github.com/a/b", question="how does auth work?")

    assert answer == "Auth is handled in auth.py:10-20."
    mock_fresh_clone.assert_called_once_with("https://github.com/a/b")
