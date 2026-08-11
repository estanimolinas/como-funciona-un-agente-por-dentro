import ReactMarkdown from 'react-markdown'

import type { StreamEvent } from '../types'

interface EventLogLineProps {
  event: StreamEvent
  isTruncatedAnswer?: boolean
}

export function EventLogLine({ event, isTruncatedAnswer }: EventLogLineProps) {
  switch (event.type) {
    case 'indexing_start':
      return (
        <div className="text-slate-400">
          Indexando {event.repo_url}...
        </div>
      )
    case 'indexing_done':
      return (
        <div className="text-slate-400">
          Indexado {event.chunk_count} chunks en {event.duration_s}s
        </div>
      )
    case 'no_semantic_index':
      return (
        <div className="flex items-start gap-2 text-amber-400">
          <span className="shrink-0">⚠</span>
          <span>{event.message}</span>
        </div>
      )
    case 'tool_call':
      return (
        <div className="flex items-start gap-2 overflow-x-auto whitespace-pre-wrap text-sky-400">
          <span className="shrink-0">→</span>
          <span>{event.tool}({JSON.stringify(event.input)})</span>
        </div>
      )
    case 'tool_result':
      return (
        <div
          className={
            'flex items-start gap-2 overflow-x-auto whitespace-pre-wrap ' +
            (event.is_error ? 'text-red-400' : 'text-emerald-400')
          }
        >
          <span className="shrink-0">{event.is_error ? '✗' : '✓'}</span>
          <span>
            {event.tool}: {event.output_preview}
            {event.is_error ? ' (error)' : ''}
          </span>
        </div>
      )
    case 'reasoning':
      return <div className="italic text-violet-400">{event.text}</div>
    case 'answer_token':
      return (
        <div>
          <ReactMarkdown>{event.text}</ReactMarkdown>
          {isTruncatedAnswer ? (
            <span className="text-amber-500"> [incompleto]</span>
          ) : null}
        </div>
      )
    case 'done':
      return null
    case 'error':
      return <div className="text-red-500">Error: {event.message}</div>
  }
}
