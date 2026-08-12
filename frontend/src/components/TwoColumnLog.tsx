import { EventLogLine } from './EventLogLine'
import { splitAgentExplanations } from '../lib/splitAgentExplanations'
import type { RunStatus, StreamEvent } from '../types'

interface TwoColumnLogProps {
  events: StreamEvent[]
  status: RunStatus
  isTruncated: boolean
}

// The orchestrator (coderag_mcp/orchestrator/ask.py) exposes search_code as an
// in-process MCP server (coderag_mcp/orchestrator/tools.py), so the tool name a
// real ToolUseBlock carries is the SDK-qualified `mcp__search__search_code`, not
// the bare `search_code` - match both so routing works against real events, not
// just the bare name a test might use. tool can be null (ask.py's
// tool_names_by_id.get() lookup miss on a tool_result), so guard for that too.
function isSearchCodeTool(tool: string | null): boolean {
  return tool !== null && (tool === 'search_code' || tool.endsWith('__search_code'))
}

function isRagEvent(event: StreamEvent): boolean {
  return (event.type === 'tool_call' || event.type === 'tool_result') && isSearchCodeTool(event.tool)
}

function isToolsEvent(event: StreamEvent): boolean {
  return (event.type === 'tool_call' || event.type === 'tool_result') && !isSearchCodeTool(event.tool)
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
        <div className="rounded border-l-4 border-emerald-600 bg-emerald-950/20 py-1 pl-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-500">
            Búsqueda semántica (RAG)
          </div>
          <div className="flex flex-col gap-2">
            {ragEvents.map((event, i) => (
              <EventLogLine key={`rag-${i}`} event={event} />
            ))}
            {ragExplanation ? (
              <EventLogLine event={{ type: 'answer_token', text: ragExplanation }} />
            ) : null}
            {status === 'done' && ragEvents.length === 0 ? (
              <div className="text-xs italic text-slate-500">
                El agente no usó búsqueda semántica para esta pregunta — fue directo a los
                archivos.
              </div>
            ) : null}
          </div>
        </div>
        <div className="rounded border-l-4 border-sky-600 bg-sky-950/20 py-1 pl-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-sky-500">
            Herramientas de archivo
          </div>
          <div className="flex flex-col gap-2">
            {toolsEvents.map((event, i) => (
              <EventLogLine key={`tools-${i}`} event={event} />
            ))}
            {toolsExplanation ? (
              <EventLogLine event={{ type: 'answer_token', text: toolsExplanation }} />
            ) : null}
            {status === 'done' && toolsEvents.length === 0 ? (
              <div className="text-xs italic text-slate-500">
                El agente no exploró archivos directamente para esta pregunta — usó solo
                búsqueda semántica.
              </div>
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
