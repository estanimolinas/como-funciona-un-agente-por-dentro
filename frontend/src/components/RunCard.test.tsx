import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunCard } from './RunCard'

function fakeResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  let i = 0
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]))
        i += 1
      } else {
        controller.close()
      }
    },
  })
  return new Response(stream, { status: 200 })
}

describe('RunCard', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the repo URL and question in the card header', async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse(['data: {"type": "done"}\n\n']))
    render(<RunCard repoUrl="https://github.com/a/b" question="How does X work?" />)

    expect(screen.getByText(/https:\/\/github.com\/a\/b/)).toBeInTheDocument()
    expect(screen.getByText(/How does X work\?/)).toBeInTheDocument()
  })

  it('concatenates answer_token events into a single growing answer', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse([
        'data: {"type": "answer_token", "text": "Auth is "}\n\n',
        'data: {"type": "answer_token", "text": "in main.py."}\n\n',
        'data: {"type": "done"}\n\n',
      ]),
    )
    render(<RunCard repoUrl="https://github.com/a/b" question="q" />)

    expect(await screen.findByText('Auth is in main.py.')).toBeInTheDocument()
  })

  it('marks a partial answer as incomplete when the stream ends in error without done', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse([
        'data: {"type": "answer_token", "text": "Partial"}\n\n',
        'data: {"type": "error", "message": "boom"}\n\n',
      ]),
    )
    render(<RunCard repoUrl="https://github.com/a/b" question="q" />)

    await screen.findByText(/boom/)
    expect(screen.getByText(/incompleto/i)).toBeInTheDocument()
  })
})
