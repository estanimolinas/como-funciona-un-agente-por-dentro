# Frontend polish — design

## Context

The frontend (React+Vite+TS+Tailwind, consuming `POST /ask/stream`) merged
to `main` and was tested live against two real repos. Against
`pypa/sampleproject` (Python), RAG worked end-to-end as designed: real
tree-sitter AST chunking, real `voyage-code-3` embeddings, real
`sqlite-vec` search, and the orchestrator genuinely called `search_code`.
Against `github.com/garrytan/gstack` (TypeScript), indexing produced
"Indexed 0 chunks" — `coderag_mcp/indexing/chunker.py` only parses `.py`
files — so `search_code` was useless and the orchestrator fell back
entirely to raw `Read`/`Grep`/`Glob`, both degrading answer quality and
producing a much noisier tool-call log than the Python case.

That session also surfaced UI polish the user wants before the next demo:
raw unrendered markdown in the final answer, a visually dense event log,
a request to color-code the agent's reasoning/thinking distinctly, and a
request for the UI copy to be in Spanish.

This spec covers a single, cohesive polish pass — no sub-project
decomposition needed, it's all frontend-adjacent work plus one small,
already-scoped backend change.

## What's in scope (and one explicit decision)

Non-Python repos: **do not add new language support.** Confirmed with the
user — detect the zero-chunks case and surface it explicitly instead of
degrading silently. Adding a TypeScript/JS tree-sitter grammar is real
scope (new dependency, new chunker path, new tests) and, if wanted later,
gets its own separate spec/plan.

1. Surface "no semantic index" explicitly (backend + frontend).
2. Render the final answer as real markdown, not raw text.
3. Color-code `reasoning` events distinctly (agent "thinking").
4. General visual cleanup of the event log.
5. Spanish UI copy.

## 1. Surface "no semantic index" explicitly

**Where the check belongs:** inside `orchestrator/ask.py`'s `ask_stream()`,
not the route. `ask_stream()` is the single place both `POST /ask/stream`
and `ask()` (in turn used by `POST /ask` and the `ask_repo` MCP tool) flow
through, so putting the check here means every caller gets the improved
behavior for free, with no duplicated logic at the route level.

At the very start of `ask_stream()`, after the existing clone step, call
`await run_db_sync(count_chunks, conn, repo_id)` (same pattern
`ask_stream_route.py` already uses for the `indexing_done` event). If the
count is `0`:
- Yield a new event `{"type": "no_semantic_index", "message": "This
  repository has no indexed code (unsupported language, or an empty/
  non-code repo) — answering by exploring files directly instead of
  semantic search."}` before entering the `query()` loop.
- Build `ClaudeAgentOptions.system_prompt` as
  `ORCHESTRATOR_SYSTEM_PROMPT` plus one appended paragraph noting that
  `search_code` has no index for this repository and will not return
  useful results, so the agent should rely on `Read`/`Grep`/`Glob`
  instead — this saves a wasted turn where the agent tries `search_code`
  first, gets nothing, then falls back anyway.

No other behavior changes: `search_code` stays in `allowed_tools`
unconditionally (removing it entirely is unnecessary — the appended
prompt guidance is enough, and keeping it available costs nothing since
`search_and_format` already handles the empty-corpus case gracefully by
returning "no results", it just isn't the *first* thing tried anymore).

**Frontend:** `types.ts` gains a `no_semantic_index` variant on
`StreamEvent`. `EventLogLine` renders it as its own amber-toned line
(reusing the existing amber accent already used for `[incomplete]`,
keeping the palette consistent) with an icon/marker distinct from a
regular status line, so it reads as "heads up" rather than blending into
the log.

## 2. Real markdown rendering for the final answer

Add `react-markdown` (`^10.1.0`, current at spec-writing time — confirm
via `npm view react-markdown version` before pinning in the plan, per this
project's established practice of verifying installed/current versions
rather than assuming). No remark/rehype plugins beyond the default (no
GFM tables/footnotes needed for this use case — YAGNI).

In `RunCard`, the merged `answer_token` text (already concatenated into
one string per the existing "single growing bubble" logic) renders through
`<ReactMarkdown>{mergedText}</ReactMarkdown>` instead of a plain text
node. The `isTruncatedAnswer` marker stays exactly as it is today — kept
as a small separate `[incomplete]` badge appended after the rendered
markdown block, not inside the markdown string itself (avoids any escaping
edge cases from mixing the marker into markdown source).

## 3. Color-code agent reasoning

`reasoning` events change from `italic text-slate-500` to
`italic text-violet-400` in `EventLogLine` — violet is unused by any other
event type today (`tool_call`: sky, `tool_result`: emerald/red,
`no_semantic_index`: amber, `error`: red, `[incomplete]`: amber) and is a
common visual convention for "the model is thinking," distinguishing it
clearly at a glance from tool activity and from the final answer.

## 4. General event log cleanup

Targeted, not a redesign:
- `tool_call`'s `JSON.stringify(event.input)` and `tool_result`'s
  `output_preview` get `overflow-x-auto` / truncation-friendly wrapping
  so a long `Grep` pattern or file path doesn't blow out the card's
  width (a real issue the final review flagged during the original
  frontend plan and deferred as cosmetic — folding it in here).
- Consistent left-icon alignment across event types (→ for tool_call, ✓/✗
  for tool_result, a distinct marker for `no_semantic_index`) using a
  shared small layout tweak in `EventLogLine` rather than per-case ad hoc
  spacing.
- Slightly increased vertical spacing between log lines in `RunCard` for
  readability (a one-line Tailwind gap adjustment, not a structural
  change).

## 5. Spanish UI copy

Direct string replacement, no i18n library (single-language local app —
adding a library for one static language would be over-engineering).
Covers `RepoForm` ("Ask" → "Preguntar", "Repo URL" → "URL del repo",
"Question" → "Pregunta", "Add API key (optional)" → "Agregar API key
(opcional)", example button prefix "Try:" → "Probar:"), `RunCard`
("Connecting..." → "Conectando...", the `[incomplete]` marker →
"[incompleto]"), and `EventLogLine`'s generated text ("Indexing..." →
"Indexando...", "Indexed N chunks in Xs" → "Indexado N chunks en Xs",
"error" suffix → "(error)" stays as-is since it's already
language-neutral, the new `no_semantic_index` message written in Spanish
from the start). Backend-emitted event `message`/`output_preview` text
that originates from the LLM or from repo content (tool results, the
final answer, the `no_semantic_index` message) — the `no_semantic_index`
message is authored fresh in Spanish since it's a static string `ask.py`
controls entirely; anything the LLM generates (the answer text, its
`reasoning`) is not translated — the model responds in whatever language
fits the question, out of scope to force here.

## Testing

- Backend: a new test for `ask_stream()` covering the zero-chunks path —
  mock `count_chunks` to return 0, assert the `no_semantic_index` event is
  yielded before any `query()` interaction, and assert the system prompt
  passed to `query()`'s `ClaudeAgentOptions` contains the appended
  no-index note. Existing non-zero-chunk tests must keep passing
  unchanged (default path unaffected).
- Frontend: `EventLogLine` gets a new render test for `no_semantic_index`
  and an updated test confirming `reasoning`'s new color class. A new
  test confirms the answer bubble renders through `react-markdown` (e.g.
  asserting `**bold**` input produces a `<strong>` in the rendered
  output, not literal asterisks). Spanish string changes get their
  existing tests' text assertions updated to match (no new test cases
  needed purely for translation, since the existing suite already
  exercises every string being changed).
- Full existing test suite (97 backend / 27 frontend) must stay green.
