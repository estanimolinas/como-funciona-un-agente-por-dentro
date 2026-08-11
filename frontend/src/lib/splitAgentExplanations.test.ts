import { describe, expect, it } from 'vitest'

import { splitAgentExplanations } from './splitAgentExplanations'

describe('splitAgentExplanations', () => {
  it('splits out both explanations when both markers are present', () => {
    const text =
      'La respuesta.\n' +
      '@@AGENTTRACE:RAG@@\n' +
      'Expliqué RAG.\n' +
      '@@AGENTTRACE:TOOLS@@\n' +
      'Expliqué tools.\n' +
      '@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe('La respuesta.')
    expect(result.ragExplanation).toBe('Expliqué RAG.')
    expect(result.toolsExplanation).toBe('Expliqué tools.')
  })

  it('splits out only the RAG explanation when only that marker is present', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:RAG@@\nExpliqué RAG.\n@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe('La respuesta.')
    expect(result.ragExplanation).toBe('Expliqué RAG.')
    expect(result.toolsExplanation).toBeNull()
  })

  it('splits out only the tools explanation when only that marker is present', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:TOOLS@@\nExpliqué tools.\n@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe('La respuesta.')
    expect(result.ragExplanation).toBeNull()
    expect(result.toolsExplanation).toBe('Expliqué tools.')
  })

  it('returns the full text as the answer with no explanations when no markers are present', () => {
    const text = 'Solo una respuesta normal, sin marcadores.'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe(text)
    expect(result.ragExplanation).toBeNull()
    expect(result.toolsExplanation).toBeNull()
  })

  it('treats an empty explanation section as null rather than an empty string', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:RAG@@\n\n@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.ragExplanation).toBeNull()
  })

  it('does not split when the END marker is missing (incomplete/partial marker text)', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:RAG@@\nTodavía escribiendo'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe(text)
    expect(result.ragExplanation).toBeNull()
  })

  it('is not fooled by a quoted marker string appearing in the real answer before the real marker block', () => {
    const text =
      'El mecanismo AgentTrace usa un marcador como @@AGENTTRACE:RAG@@ para separar ' +
      'secciones.\n' +
      '@@AGENTTRACE:RAG@@\n' +
      'Expliqué RAG.\n' +
      '@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe(
      'El mecanismo AgentTrace usa un marcador como @@AGENTTRACE:RAG@@ para separar secciones.',
    )
    expect(result.ragExplanation).toBe('Expliqué RAG.')
    expect(result.toolsExplanation).toBeNull()
  })
})
