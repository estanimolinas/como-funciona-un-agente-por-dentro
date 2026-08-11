export interface AgentExplanations {
  answer: string
  ragExplanation: string | null
  toolsExplanation: string | null
}

const RAG_MARKER = '@@AGENTTRACE:RAG@@'
const TOOLS_MARKER = '@@AGENTTRACE:TOOLS@@'
const END_MARKER = '@@AGENTTRACE:END@@'

export function splitAgentExplanations(fullAnswerText: string): AgentExplanations {
  const ragIndex = fullAnswerText.indexOf(RAG_MARKER)
  const toolsIndex = fullAnswerText.indexOf(TOOLS_MARKER)
  const endIndex = fullAnswerText.indexOf(END_MARKER)

  if (endIndex === -1 || (ragIndex === -1 && toolsIndex === -1)) {
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
