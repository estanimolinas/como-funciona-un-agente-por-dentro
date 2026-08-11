export type StreamEvent =
  | { type: 'indexing_start'; repo_url: string }
  | { type: 'indexing_done'; chunk_count: number; duration_s: number }
  | { type: 'no_semantic_index'; message: string }
  | { type: 'tool_call'; tool: string; input: Record<string, unknown> }
  | {
      // ask.py's tool_names_by_id.get(block.tool_use_id) can miss and return
      // None on the backend - reflect that here rather than lying with `string`.
      type: 'tool_result'
      tool: string | null
      tool_use_id: string
      output_preview: string
      is_error: boolean | null
    }
  | { type: 'reasoning'; text: string }
  | { type: 'answer_token'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

export type RunStatus = 'connecting' | 'streaming' | 'done' | 'error'

export interface AskStreamParams {
  repoUrl: string
  question: string
  apiKey?: string
}
