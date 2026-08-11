import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EventLogLine } from './EventLogLine'
import type { StreamEvent } from '../types'

describe('EventLogLine', () => {
  it('renders indexing_start', () => {
    render(<EventLogLine event={{ type: 'indexing_start', repo_url: 'https://github.com/a/b' }} />)
    expect(screen.getByText(/indexing/i)).toBeInTheDocument()
    expect(screen.getByText(/a\/b|https:\/\/github.com\/a\/b/)).toBeInTheDocument()
  })

  it('renders indexing_done with chunk count and duration', () => {
    render(<EventLogLine event={{ type: 'indexing_done', chunk_count: 42, duration_s: 3.2 }} />)
    expect(screen.getByText(/42/)).toBeInTheDocument()
    expect(screen.getByText(/3\.2/)).toBeInTheDocument()
  })

  it('renders tool_call with tool name and input', () => {
    const event: StreamEvent = { type: 'tool_call', tool: 'search_code', input: { query: 'auth' } }
    render(<EventLogLine event={event} />)
    expect(screen.getByText(/search_code/)).toBeInTheDocument()
    expect(screen.getByText(/auth/)).toBeInTheDocument()
  })

  it('renders a successful tool_result', () => {
    const event: StreamEvent = {
      type: 'tool_result',
      tool: 'search_code',
      tool_use_id: 'toolu_1',
      output_preview: 'found 3 matches',
      is_error: false,
    }
    render(<EventLogLine event={event} />)
    expect(screen.getByText(/search_code/)).toBeInTheDocument()
    expect(screen.getByText(/found 3 matches/)).toBeInTheDocument()
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
  })

  it('renders a failed tool_result with an error indicator', () => {
    const event: StreamEvent = {
      type: 'tool_result',
      tool: 'Read',
      tool_use_id: 'toolu_2',
      output_preview: 'No such file',
      is_error: true,
    }
    render(<EventLogLine event={event} />)
    expect(screen.getByText(/error/i)).toBeInTheDocument()
  })

  it('renders reasoning text', () => {
    render(<EventLogLine event={{ type: 'reasoning', text: 'thinking about auth' }} />)
    expect(screen.getByText(/thinking about auth/)).toBeInTheDocument()
  })

  it('renders an answer_token', () => {
    render(<EventLogLine event={{ type: 'answer_token', text: 'Auth is ' }} />)
    expect(screen.getByText(/Auth is/)).toBeInTheDocument()
  })

  it('renders an error event', () => {
    render(<EventLogLine event={{ type: 'error', message: 'Something broke' }} />)
    expect(screen.getByText(/Something broke/)).toBeInTheDocument()
  })

  it('marks an answer_token as truncated when isTruncatedAnswer is set', () => {
    render(
      <EventLogLine
        event={{ type: 'answer_token', text: 'partial answer' }}
        isTruncatedAnswer
      />,
    )
    expect(screen.getByText(/incomplete/i)).toBeInTheDocument()
  })

  it('renders nothing visible for a done event', () => {
    const { container } = render(<EventLogLine event={{ type: 'done' }} />)
    expect(container.textContent).toBe('')
  })
})
