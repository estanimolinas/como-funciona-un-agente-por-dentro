import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TwoColumnLog } from './TwoColumnLog'
import type { StreamEvent } from '../types'

describe('TwoColumnLog', () => {
  it('routes a search_code tool_call/result pair into the RAG column', () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'search_code', input: { query: 'auth' } },
      {
        type: 'tool_result',
        tool: 'search_code',
        tool_use_id: 'toolu_1',
        output_preview: 'found it',
        is_error: false,
      },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(screen.getAllByText(/search_code/).length).toBeGreaterThan(0)
    expect(screen.getByText(/found it/)).toBeInTheDocument()
  })

  it('routes a Read/Grep/Glob tool_call/result pair into the Tools column', () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'Grep', input: { pattern: 'foo' } },
      {
        type: 'tool_result',
        tool: 'Grep',
        tool_use_id: 'toolu_2',
        output_preview: 'main.py:3:foo',
        is_error: false,
      },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(screen.getAllByText(/Grep/).length).toBeGreaterThan(0)
    expect(screen.getByText(/main\.py:3:foo/)).toBeInTheDocument()
  })

  it('renders reasoning, indexing, and no_semantic_index events outside either column', () => {
    const events: StreamEvent[] = [
      { type: 'reasoning', text: 'Thinking about the approach.' },
      { type: 'indexing_done', chunk_count: 5, duration_s: 1.2 },
      { type: 'no_semantic_index', message: 'Sin indice para este repo.' },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(screen.getByText(/Thinking about the approach/)).toBeInTheDocument()
    expect(screen.getByText(/Indexado 5 chunks/)).toBeInTheDocument()
    expect(screen.getByText(/Sin indice para este repo/)).toBeInTheDocument()
  })

  it('renders the merged answer in a full-width area', async () => {
    const events: StreamEvent[] = [
      { type: 'answer_token', text: 'La respuesta es ' },
      { type: 'answer_token', text: 'cuarenta y dos.' },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(await screen.findByText('La respuesta es cuarenta y dos.')).toBeInTheDocument()
  })

  it('leaves the RAG column visibly present but empty when no search_code events occurred', () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'Read', input: { file_path: 'main.py' } },
      {
        type: 'tool_result',
        tool: 'Read',
        tool_use_id: 'toolu_3',
        output_preview: 'print("hi")',
        is_error: false,
      },
    ]
    const { container } = render(
      <TwoColumnLog events={events} status="streaming" isTruncated={false} />,
    )
    expect(screen.queryByText(/search_code/)).not.toBeInTheDocument()
    expect(screen.getByText(/búsqueda semántica/i)).toBeInTheDocument()
    expect(container.textContent).toContain('Herramientas de archivo')
  })

  it('renders a per-column agent explanation when markers are present in the answer', async () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'search_code', input: { query: 'auth' } },
      {
        type: 'tool_result',
        tool: 'search_code',
        tool_use_id: 'toolu_1',
        output_preview: 'found it',
        is_error: false,
      },
      {
        type: 'answer_token',
        text:
          'Auth se maneja en auth.py.\n' +
          '@@AGENTTRACE:RAG@@\n' +
          'Usé búsqueda semántica porque la pregunta era conceptual.\n' +
          '@@AGENTTRACE:END@@',
      },
    ]
    render(<TwoColumnLog events={events} status="done" isTruncated={false} />)
    expect(
      await screen.findByText(/Usé búsqueda semántica porque la pregunta era conceptual/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Auth se maneja en auth\.py/)).toBeInTheDocument()
    expect(screen.queryByText(/@@AGENTTRACE/)).not.toBeInTheDocument()
  })

  it('routes an MCP-qualified search_code tool name (mcp__search__search_code) into the RAG column', () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'mcp__search__search_code', input: { query: 'auth' } },
      {
        type: 'tool_result',
        tool: 'mcp__search__search_code',
        tool_use_id: 'toolu_1',
        output_preview: 'found it',
        is_error: false,
      },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(screen.getAllByText(/mcp__search__search_code/).length).toBeGreaterThan(0)
    // Confirm it landed in the RAG column specifically, not just anywhere in the DOM
    // (the review flagged that existing routing tests were document-scoped, not
    // column-scoped, which is exactly the gap that let this bug through).
    const ragHeading = screen.getByText(/búsqueda semántica/i)
    const ragColumn = ragHeading.parentElement
    expect(ragColumn?.textContent).toContain('mcp__search__search_code')
    const toolsHeading = screen.getByText(/herramientas de archivo/i)
    const toolsColumn = toolsHeading.parentElement
    expect(toolsColumn?.textContent).not.toContain('mcp__search__search_code')
  })

  it('shows a connecting status line while status is connecting', () => {
    render(<TwoColumnLog events={[]} status="connecting" isTruncated={false} />)
    expect(screen.getByText(/conectando/i)).toBeInTheDocument()
  })
})
