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
  // Holds the reader for whichever run is currently in flight, so cleanup
  // (below) can actually cancel it — the reader itself is only created
  // inside the async `run()` function, after at least one await, so there's
  // no other way for the effect's cleanup closure to reach it.
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null)

  useEffect(() => {
    if (params === null) {
      return
    }

    // A fresh closure variable per effect invocation — NOT a ref reset at
    // the top of every run. A ref shared across runs would be un-done by
    // the very next run's setup (run N+1's body resets it to false right
    // after run N's cleanup set it to true), so a stale run N could keep
    // writing into run N+1's state. This `cancelled` binding belongs only
    // to this invocation of the effect and is never touched by any other
    // invocation, so run N's cleanup permanently and exclusively marks run
    // N's own closure as cancelled.
    let cancelled = false
    setEvents([])
    setStatus('connecting')

    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (params.apiKey) {
      headers['X-API-Key'] = params.apiKey
    }

    // This run's own reader, tracked locally (not just via readerRef) so
    // this run's `finally` can tell whether `readerRef.current` still
    // points at ITS reader before clearing it — otherwise, if this run's
    // async work is still unwinding after cleanup already swapped in a
    // newer run's reader (see the cleanup function below), this `finally`
    // could null out the newer run's reference instead of its own.
    let myReader: ReadableStreamDefaultReader<Uint8Array> | null = null

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

        if (cancelled) return
        setStatus('streaming')

        const reader = response.body.getReader()
        myReader = reader
        readerRef.current = reader
        const decoder = new TextDecoder()
        let buffer = ''
        let sawTerminal = false

        while (true) {
          const result = await readWithTimeout(reader, INACTIVITY_TIMEOUT_MS)
          if (cancelled) return
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

            if (cancelled) return

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

        if (!sawTerminal && !cancelled) {
          setStatus('error')
          setEvents((prev) => [...prev, { type: 'error', message: 'Connection lost' }])
        }
      } catch (err) {
        if (cancelled) return
        const message = err instanceof Error ? err.message : String(err)
        setStatus('error')
        setEvents((prev) => [...prev, { type: 'error', message }])
      } finally {
        if (readerRef.current === myReader) {
          readerRef.current = null
        }
      }
    }

    void run()

    return () => {
      cancelled = true
      // Actually stop the underlying network read, not just suppress
      // further state writes — otherwise the fetch/read loop (and any live
      // readWithTimeout timer) keeps running in the background until the
      // server closes the stream or the 30s inactivity timeout fires.
      // reader.cancel() is safe to call even if the reader is mid-read or
      // already closed/errored.
      readerRef.current?.cancel().catch(() => {
        // Nothing to do — we're tearing down this run anyway.
      })
      readerRef.current = null
    }
  }, [params])

  return { events, status }
}
