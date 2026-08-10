from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT


def test_system_prompt_mentions_both_tool_families():
    assert "search_code" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Read" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Grep" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Glob" in ORCHESTRATOR_SYSTEM_PROMPT
