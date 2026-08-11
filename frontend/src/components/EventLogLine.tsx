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
          Indexing {event.repo_url}...
        </div>
      )
    case 'indexing_done':
      return (
        <div className="text-slate-400">
          Indexed {event.chunk_count} chunks in {event.duration_s}s
        </div>
      )
    case 'no_semantic_index':
      return <div className="text-amber-400">⚠ {event.message}</div>
    case 'tool_call':
      return (
        <div className="text-sky-400">
          → {event.tool}({JSON.stringify(event.input)})
        </div>
      )
    case 'tool_result':
      return (
        <div className={event.is_error ? 'text-red-400' : 'text-emerald-400'}>
          {event.is_error ? '✗' : '✓'} {event.tool}: {event.output_preview}
          {event.is_error ? ' (error)' : ''}
        </div>
      )
    case 'reasoning':
      return <div className="italic text-slate-500">{event.text}</div>
    case 'answer_token':
      return (
        <div>
          <ReactMarkdown>{event.text}</ReactMarkdown>
          {isTruncatedAnswer ? (
            <span className="text-amber-500"> [incomplete]</span>
          ) : null}
        </div>
      )
    case 'done':
      return null
    case 'error':
      return <div className="text-red-500">Error: {event.message}</div>
  }
}
