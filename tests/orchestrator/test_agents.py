from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT


def test_system_prompt_mentions_both_tool_families():
    assert "search_code" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Read" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Grep" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Glob" in ORCHESTRATOR_SYSTEM_PROMPT


def test_system_prompt_instructs_the_agent_to_emit_method_explanation_markers():
    assert "@@AGENTTRACE:RAG@@" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "@@AGENTTRACE:TOOLS@@" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "@@AGENTTRACE:END@@" in ORCHESTRATOR_SYSTEM_PROMPT
