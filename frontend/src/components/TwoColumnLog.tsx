import { EventLogLine } from './EventLogLine'
import { splitAgentExplanations } from '../lib/splitAgentExplanations'
import type { RunStatus, StreamEvent } from '../types'

interface TwoColumnLogProps {
  events: StreamEvent[]
  status: RunStatus
  isTruncated: boolean
}

function isRagEvent(event: StreamEvent): boolean {
  return (
    (event.type === 'tool_call' || event.type === 'tool_result') && event.tool === 'search_code'
  )
}

function isToolsEvent(event: StreamEvent): boolean {
  return (
    (event.type === 'tool_call' || event.type === 'tool_result') && event.tool !== 'search_code'
  )
}

export function TwoColumnLog({ events, status, isTruncated }: TwoColumnLogProps) {
  const statusEvents = events.filter(
    (e) =>
      e.type === 'indexing_start' ||
      e.type === 'indexing_done' ||
      e.type === 'no_semantic_index' ||
      e.type === 'error',
  )
  const reasoningEvents = events.filter((e) => e.type === 'reasoning')
  const ragEvents = events.filter(isRagEvent)
  const toolsEvents = events.filter(isToolsEvent)

  const fullAnswerText = events
    .filter((e): e is Extract<StreamEvent, { type: 'answer_token' }> => e.type === 'answer_token')
    .map((e) => e.text)
    .join('')
  const { answer, ragExplanation, toolsExplanation } = splitAgentExplanations(fullAnswerText)

  return (
    <div className="flex flex-col gap-2 font-mono text-sm">
      {status === 'connecting' ? <div className="text-slate-500">Conectando...</div> : null}
      {statusEvents.map((event, i) => (
        <EventLogLine key={`status-${i}`} event={event} />
      ))}
      {reasoningEvents.map((event, i) => (
        <EventLogLine key={`reasoning-${i}`} event={event} />
      ))}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Búsqueda semántica
          </div>
          <div className="flex flex-col gap-2">
            {ragEvents.map((event, i) => (
              <EventLogLine key={`rag-${i}`} event={event} />
            ))}
            {ragExplanation ? (
              <EventLogLine event={{ type: 'answer_token', text: ragExplanation }} />
            ) : null}
          </div>
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Herramientas de archivo
          </div>
          <div className="flex flex-col gap-2">
            {toolsEvents.map((event, i) => (
              <EventLogLine key={`tools-${i}`} event={event} />
            ))}
            {toolsExplanation ? (
              <EventLogLine event={{ type: 'answer_token', text: toolsExplanation }} />
            ) : null}
          </div>
        </div>
      </div>
      {answer ? (
        <EventLogLine event={{ type: 'answer_token', text: answer }} isTruncatedAnswer={isTruncated} />
      ) : null}
    </div>
  )
}
