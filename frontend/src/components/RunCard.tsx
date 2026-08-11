import { useMemo } from 'react'

import { useAskStream } from '../hooks/useAskStream'
import { EventLogLine } from './EventLogLine'
import type { AskStreamParams, StreamEvent } from '../types'

interface RunCardProps {
  repoUrl: string
  question: string
  apiKey?: string
}

export function RunCard({ repoUrl, question, apiKey }: RunCardProps) {
  // Built once (useMemo with an empty dep array) so useAskStream sees a
  // stable params identity for this card's whole lifetime and never
  // reopens the connection — see useAskStream's Task 2 contract.
  const params: AskStreamParams = useMemo(
    () => ({ repoUrl, question, apiKey }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const { events, status } = useAskStream(params)

  const hasDone = events.some((e) => e.type === 'done')
  const hasError = events.some((e) => e.type === 'error')
  const isTruncated = hasError && !hasDone

  // answer_token events arrive one token at a time and are meant to read
  // as a single growing answer, not one log line per token — accumulate
  // consecutive runs of them into a single synthetic event so EventLogLine
  // renders one merged text node per run, while every other event type
  // still gets its own line in original order.
  const renderItems: { key: string; event: StreamEvent }[] = []
  let pendingAnswer = ''
  let pendingKey: string | null = null
  events.forEach((event, i) => {
    if (event.type === 'answer_token') {
      pendingAnswer += event.text
      pendingKey ??= `answer-${i}`
    } else {
      if (pendingKey !== null) {
        renderItems.push({ key: pendingKey, event: { type: 'answer_token', text: pendingAnswer } })
        pendingAnswer = ''
        pendingKey = null
      }
      renderItems.push({ key: String(i), event })
    }
  })
  if (pendingKey !== null) {
    renderItems.push({ key: pendingKey, event: { type: 'answer_token', text: pendingAnswer } })
  }

  return (
    <div className="rounded border border-slate-800 p-4">
      <div className="mb-2 text-sm text-slate-400">
        {repoUrl} — {question}
      </div>
      <div className="flex flex-col gap-1 font-mono text-sm">
        {status === 'connecting' ? <div className="text-slate-500">Connecting...</div> : null}
        {renderItems.map(({ key, event }) => (
          <EventLogLine
            key={key}
            event={event}
            isTruncatedAnswer={isTruncated && event.type === 'answer_token'}
          />
        ))}
      </div>
    </div>
  )
}
