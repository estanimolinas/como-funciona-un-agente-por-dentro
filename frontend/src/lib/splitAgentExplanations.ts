export interface AgentExplanations {
  answer: string
  ragExplanation: string | null
  toolsExplanation: string | null
}

// These marker strings are a cross-layer contract with the backend's system
// prompt (coderag_mcp/orchestrator/agents.py's ORCHESTRATOR_SYSTEM_PROMPT) -
// changing them here without changing them there (or vice versa) silently
// breaks marker parsing with no test failure on either side, since the two
// layers aren't otherwise linked.
const RAG_MARKER = '@@AGENTTRACE:RAG@@'
const TOOLS_MARKER = '@@AGENTTRACE:TOOLS@@'
const END_MARKER = '@@AGENTTRACE:END@@'

export function splitAgentExplanations(fullAnswerText: string): AgentExplanations {
  // Anchor to the LAST occurrence of each marker, searching backward from the
  // last END marker. The real marker block always sits immediately before END,
  // so the occurrence closest to (but before) END is the structural one. If the
  // model's answer text ever quotes one of these literal marker strings earlier
  // (e.g. explaining this very mechanism), that quoted occurrence is further
  // from END than the real one and must not be mistaken for it, or it would
  // truncate the real answer at the wrong point.
  const endIndex = fullAnswerText.lastIndexOf(END_MARKER)

  if (endIndex === -1) {
    return { answer: fullAnswerText, ragExplanation: null, toolsExplanation: null }
  }

  const ragIndex = fullAnswerText.lastIndexOf(RAG_MARKER, endIndex - 1)
  const toolsIndex = fullAnswerText.lastIndexOf(TOOLS_MARKER, endIndex - 1)

  if (ragIndex === -1 && toolsIndex === -1) {
    return { answer: fullAnswerText, ragExplanation: null, toolsExplanation: null }
  }

  const markerIndices = [ragIndex, toolsIndex].filter((i) => i !== -1).sort((a, b) => a - b)
  const answer = fullAnswerText.slice(0, markerIndices[0]).trim()

  let ragExplanation: string | null = null
  let toolsExplanation: string | null = null

  if (ragIndex !== -1) {
    const ragEnd = toolsIndex !== -1 && toolsIndex > ragIndex ? toolsIndex : endIndex
    ragExplanation = fullAnswerText.slice(ragIndex + RAG_MARKER.length, ragEnd).trim() || null
  }

  if (toolsIndex !== -1) {
    const toolsEnd = ragIndex !== -1 && ragIndex > toolsIndex ? ragIndex : endIndex
    toolsExplanation = fullAnswerText.slice(toolsIndex + TOOLS_MARKER.length, toolsEnd).trim() || null
  }

  return { answer, ragExplanation, toolsExplanation }
}
