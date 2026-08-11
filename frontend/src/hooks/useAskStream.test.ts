import { StrictMode } from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAskStream } from './useAskStream'

function fakeResponse(chunks: string[], status = 200): Response {
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
  return new Response(stream, { status })
}

describe('useAskStream', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // NOTE: every test below hoists its `params` object to a `const` outside
  // the `renderHook` callback, instead of constructing it inline as
  // `renderHook(() => useAskStream({ ... }))`. This matters because the
  // hook's effect deps are `[params]` (intentional reference-equality per
  // its contract — see useAskStream.ts's docstring: it must NOT reopen the
  // connection just because a render happened, only when the caller
  // supplies a genuinely new params object, as Task 5's RunCard does by
  // creating params once per card at mount). If `params` were constructed
  // inline inside the renderHook callback, React would build a brand-new
  // object on every re-render of the underlying test component — including
  // the re-renders the hook's own setEvents/setStatus calls trigger — so
  // the effect would see a "new" params object each time, tear down and
  // refire, refetch, update state, re-render, and repeat forever. That is
  // an infinite loop, not just a slow test: it was verified to reliably
  // exhaust the Vitest worker's heap (OOM crash) for every test in this
  // file, not only the timeout one. Hoisting `params` (mirroring how a real
  // caller is supposed to memoize it) keeps its identity stable across
  // re-renders and avoids the loop entirely.

  it('parses whole SSE frames delivered in separate chunks', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse([
        'data: {"type": "tool_call", "tool": "Glob", "input": {"pattern": "*.py"}}\n\n',
        'data: {"type": "done"}\n\n',
      ]),
    )

    const params = { repoUrl: 'https://github.com/a/b', question: 'q' }
    const { result } = renderHook(() => useAskStream(params))

    await waitFor(() => expect(result.current.status).toBe('done'))
    expect(result.current.events).toEqual([
      { type: 'tool_call', tool: 'Glob', input: { pattern: '*.py' } },
      { type: 'done' },
    ])
  })

  it('parses a single SSE frame split across two chunks', async () => {
    const frame = 'data: {"type": "answer_token", "text": "hello"}\n\n'
    const splitPoint = 20 // splits mid-JSON, well inside the frame
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse([
        frame.slice(0, splitPoint),
        frame.slice(splitPoint) + 'data: {"type": "done"}\n\n',
      ]),
    )

    const params = { repoUrl: 'https://github.com/a/b', question: 'q' }
    const { result } = renderHook(() => useAskStream(params))

    await waitFor(() => expect(result.current.status).toBe('done'))
    expect(result.current.events).toEqual([
      { type: 'answer_token', text: 'hello' },
      { type: 'done' },
    ])
  })

  it('sends X-API-Key header only when an apiKey is provided', async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse(['data: {"type": "done"}\n\n']))

    const params = { repoUrl: 'https://github.com/a/b', question: 'q', apiKey: 'secret' }
    renderHook(() => useAskStream(params))

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect((init?.headers as Record<string, string>)['X-API-Key']).toBe('secret')
  })

  it('marks status as error when the stream ends with an error event', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(['data: {"type": "error", "message": "boom"}\n\n']),
    )

    const params = { repoUrl: 'https://github.com/a/b', question: 'q' }
    const { result } = renderHook(() => useAskStream(params))

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.events).toEqual([{ type: 'error', message: 'boom' }])
  })

  it('marks status as error when fetch itself rejects', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))

    const params = { repoUrl: 'https://github.com/a/b', question: 'q' }
    const { result } = renderHook(() => useAskStream(params))

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.events).toEqual([
      { type: 'error', message: 'Failed to fetch' },
    ])
  })

  it('does nothing when params is null', () => {
    const { result } = renderHook(() => useAskStream(null))
    expect(fetch).not.toHaveBeenCalled()
    expect(result.current).toEqual({ events: [], status: 'connecting' })
  })

  it('does not reopen the connection on a re-render with a reference-equal params object', async () => {
    // Proves the spec-mandated behavior directly: a re-render that passes
    // the *same* params object (by reference) must not cause the effect to
    // tear down and refire. This only holds because of React's normal
    // dependency-array semantics (`[params]` compared by `Object.is`) — the
    // hook does nothing special beyond relying on that. If a future change
    // ever swapped the effect deps for something that re-derives equality
    // structurally (or added a field to the deps array that isn't part of
    // `params`), this test would catch the regression.
    vi.mocked(fetch).mockResolvedValue(fakeResponse(['data: {"type": "done"}\n\n']))

    const params = { repoUrl: 'https://github.com/a/b', question: 'q' }
    const { result, rerender } = renderHook(() => useAskStream(params))

    await waitFor(() => expect(result.current.status).toBe('done'))
    expect(fetch).toHaveBeenCalledTimes(1)

    // Re-render the same hook instance, passing the identical params
    // reference again (not a new object with equal fields).
    rerender()
    rerender()

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(result.current.status).toBe('done')
    expect(result.current.events).toEqual([{ type: 'done' }])
  })

  it('marks the connection as lost after 30s of no frames', async () => {
    // NOTE: adjusted from the brief's version in two ways.
    //
    // 1. `params` is hoisted to a `const` outside the renderHook callback,
    //    same as every other test above — see the comment near the top of
    //    this file. Without that, this test (and every other test in this
    //    file) reliably crashed the Vitest worker with a JS heap OOM: an
    //    inline params object gets rebuilt on every re-render, the effect's
    //    `[params]` dep sees a "new" object each time, and the resulting
    //    refetch -> state update -> re-render -> refetch cycle never
    //    terminates. This was root-caused with an isolated reproduction
    //    (reproduces even with plain real timers, unrelated to fake timers
    //    or the hung ReadableStream below) and is the same fix applied to
    //    every other test in this file.
    //
    // 2. `vi.useFakeTimers()` is not used at all. It was tried (both
    //    unscoped and scoped to `toFake: ['setTimeout', 'clearTimeout']`),
    //    but reliably starved React's own re-render scheduling in this
    //    jsdom setup: `setStatus('streaming')` — which does not even
    //    involve the hook's 30s timer — never became visible via
    //    `result.current`, even after advancing the fake clock or awaiting
    //    extra microtask ticks, and even a real-time `waitFor` timed out
    //    while fake timers were active. Confirmed by re-running the exact
    //    same assertions with fake timers removed: `result.current.status`
    //    reaches 'streaming' immediately. So the fix here is to leave
    //    global timers real (React's scheduler and `waitFor`'s polling both
    //    need them) and instead scope the fake-time control to just the
    //    hook's own 30s `setTimeout(..., 30_000)` call, via a `setTimeout`
    //    spy that only intercepts calls with that exact delay and passes
    //    every other call through to the real `setTimeout` unchanged. This
    //    still proves the exact behavior the brief's version intended — a
    //    stalled connection with no frames for 30s gets marked as a
    //    lost-connection error — without waiting 30 real seconds and
    //    without needing the fake-timer engine at all.
    const originalSetTimeout = globalThis.setTimeout
    let inactivityCallback: (() => void) | null = null
    const setTimeoutSpy = vi
      .spyOn(globalThis, 'setTimeout')
      .mockImplementation(((cb: () => void, ms?: number, ...rest: unknown[]) => {
        if (ms === 30_000) {
          inactivityCallback = cb
          return 0 as unknown as ReturnType<typeof setTimeout>
        }
        return originalSetTimeout(cb, ms, ...rest)
      }) as typeof setTimeout)

    // A stream that enqueues nothing and never closes - simulates a hung
    // connection (the encoder/controller are never used, only kept so the
    // ReadableStream type-checks).
    const stream = new ReadableStream<Uint8Array>({
      pull() {
        // never resolves - the pull promise stays pending forever
      },
    })
    vi.mocked(fetch).mockResolvedValue(new Response(stream, { status: 200 }))

    const params = { repoUrl: 'https://github.com/a/b', question: 'q' }
    const { result } = renderHook(() => useAskStream(params))

    await waitFor(() => expect(result.current.status).toBe('streaming'))
    await waitFor(() => expect(inactivityCallback).not.toBeNull())

    inactivityCallback!()

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.events).toEqual([
      { type: 'error', message: 'Connection lost' },
    ])

    setTimeoutSpy.mockRestore()
  })

  it('aborts the discarded first request under StrictMode double-invocation', async () => {
    // Regression test for a real bug: the app renders <App /> inside
    // <StrictMode> (see main.tsx), which double-invokes every effect
    // (setup -> cleanup -> setup) in dev mode to surface cleanup bugs.
    // React runs this synchronously as part of mount, so `fetch()` is
    // genuinely called twice — that part can't be (and shouldn't be)
    // avoided. What the bug was: the *first* invocation's cleanup could
    // not actually cancel its fetch (readerRef.current was still null —
    // the reader is only created after the fetch promise resolves), so the
    // discarded first request's server-side work (a full clone + embed +
    // orchestrator run) kept running to completion for nobody. The fix
    // uses an AbortController created at the top of the effect and aborted
    // in cleanup, which works even before a reader exists — proven here by
    // asserting the *first* call's signal was actually aborted, while the
    // surviving second call was not, and that the hook's final state
    // reflects only the second (real) run, with no spurious 'error' event
    // from the aborted first one. `renderHook`/`render` don't wrap in
    // StrictMode by default, so this must be done explicitly via the
    // `wrapper` option — the existing suite's plain `renderHook` calls
    // would never have caught this.
    //
    // The mock must actually honor the AbortSignal passed in fetch's
    // `init`, the same way a real fetch would — otherwise this test can't
    // distinguish "the discarded first request got cancelled" (the fix)
    // from "the discarded first request ran to completion but its result
    // was merely ignored" (the bug), since vi.fn()'s default
    // mockResolvedValue ignores the signal entirely.
    vi.mocked(fetch).mockImplementation(
      (_input, init) =>
        new Promise((resolve, reject) => {
          const signal = init?.signal
          if (signal?.aborted) {
            reject(new DOMException('Aborted', 'AbortError'))
            return
          }
          signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'))
          })
          resolve(
            fakeResponse([
              'data: {"type": "answer_token", "text": "hi"}\n\n',
              'data: {"type": "done"}\n\n',
            ]),
          )
        }),
    )

    const params = { repoUrl: 'https://github.com/a/b', question: 'q' }
    const { result } = renderHook(() => useAskStream(params), {
      wrapper: StrictMode,
    })

    await waitFor(() => expect(result.current.status).toBe('done'))

    expect(fetch).toHaveBeenCalledTimes(2)
    const [, firstInit] = vi.mocked(fetch).mock.calls[0]
    const [, secondInit] = vi.mocked(fetch).mock.calls[1]
    expect(firstInit?.signal?.aborted).toBe(true)
    expect(secondInit?.signal?.aborted).toBe(false)

    // Only the surviving (second) request's events should be reflected —
    // no leftover/duplicate/error state from the aborted first request.
    expect(result.current.events).toEqual([
      { type: 'answer_token', text: 'hi' },
      { type: 'done' },
    ])
  })
})
