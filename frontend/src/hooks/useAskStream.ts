import { useEffect, useRef, useState } from 'react'

import type { AskStreamParams, RunStatus, StreamEvent } from '../types'

interface AskStreamResult {
  events: StreamEvent[]
  status: RunStatus
}

const INACTIVITY_TIMEOUT_MS = 30_000

type ReadResult = ReadableStreamReadResult<Uint8Array> | 'timeout'

async function readWithTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  ms: number,
): Promise<ReadResult> {
  let timeoutId: ReturnType<typeof setTimeout>
  const timeoutPromise = new Promise<'timeout'>((resolve) => {
    timeoutId = setTimeout(() => resolve('timeout'), ms)
  })
  try {
    return await Promise.race([reader.read(), timeoutPromise])
  } finally {
    clearTimeout(timeoutId!)
  }
}

export function useAskStream(params: AskStreamParams | null): AskStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [status, setStatus] = useState<RunStatus>('connecting')
  // Guards against setting state after the params identity changes (e.g. a
  // fast unmount) — this hook does not reopen a connection for a given
  // params object, so a stale in-flight read must not clobber a later run's
  // state if this hook instance were ever reused, which callers avoid by
  // always mounting a fresh RunCard per run (see Task 5).
  const cancelledRef = useRef(false)

  useEffect(() => {
    if (params === null) {
      return
    }

    cancelledRef.current = false
    setEvents([])
    setStatus('connecting')

    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (params.apiKey) {
      headers['X-API-Key'] = params.apiKey
    }

    async function run() {
      try {
        const response = await fetch('/ask/stream', {
          method: 'POST',
          headers,
          body: JSON.stringify({ repo_url: params!.repoUrl, question: params!.question }),
        })

        if (!response.body) {
          throw new Error('Response has no body')
        }

        setStatus('streaming')

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let sawTerminal = false

        while (true) {
          const result = await readWithTimeout(reader, INACTIVITY_TIMEOUT_MS)
          if (result === 'timeout') {
            await reader.cancel()
            throw new Error('Connection lost')
          }
          const { done: streamDone, value } = result
          if (streamDone) break

          buffer += decoder.decode(value, { stream: true })
          const frames = buffer.split('\n\n')
          buffer = frames.pop() ?? ''

          for (const frame of frames) {
            const line = frame.trim()
            if (!line.startsWith('data:')) continue
            const jsonText = line.slice('data:'.length).trim()
            const event = JSON.parse(jsonText) as StreamEvent

            if (cancelledRef.current) return

            setEvents((prev) => [...prev, event])
            if (event.type === 'done') {
              sawTerminal = true
              setStatus('done')
            } else if (event.type === 'error') {
              sawTerminal = true
              setStatus('error')
            }
          }
        }

        if (!sawTerminal && !cancelledRef.current) {
          setStatus('error')
          setEvents((prev) => [...prev, { type: 'error', message: 'Connection lost' }])
        }
      } catch (err) {
        if (cancelledRef.current) return
        const message = err instanceof Error ? err.message : String(err)
        setStatus('error')
        setEvents((prev) => [...prev, { type: 'error', message }])
      }
    }

    void run()

    return () => {
      cancelledRef.current = true
    }
  }, [params])

  return { events, status }
}
