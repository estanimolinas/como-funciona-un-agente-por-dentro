# AgentTrace clarity redesign — design

## Context

After four prior frontend plans (initial build, gitingest-style visual
redesign, frontend polish, UX polish fixes), the user personally used the
live app end-to-end multiple times and gave hard, honest product feedback:
the name overpromises, it's unclear whether semantic search actually
happened in a given run, there's no way to respond when the agent asks a
clarifying question, the Python-only limitation isn't stated upfront, the
optional API key field's purpose is still unclear despite existing help
text, and the whole page reads as one undifferentiated vertical column —
net result, the product doesn't clearly communicate what makes it
different from "just an LLM."

This is the first of two sub-projects agreed with the user to address
this feedback, sequenced deliberately: this one (naming + layout +
product-communication clarity) lands first; a second, larger sub-project
(real multi-turn conversation — a genuine backend architecture change
requiring session/context handling) follows afterward, once the product
actually communicates what it does today before adding the ability to
have a back-and-forth about it. This sub-project is almost entirely
frontend, with one small, contained backend touch: an addition to the
orchestrator's system prompt (see "Per-column agent explanation" below)
— no other backend behavior changes.

## Rename: coderag-mcp → AgentTrace

**User-facing branding only.** The Python package (`coderag_mcp/`), its
internal imports, the git repository name, and `pyproject.toml`'s project
name are unchanged — renaming those is a large, risky refactor with no
benefit to anyone outside the codebase, and was explicitly scoped out as
its own separate (and not currently planned) effort.

Changed:
- `frontend/index.html`'s `<title>`.
- `frontend/src/App.tsx`'s wordmark (currently `code` + coral `rag` +
  `-mcp`, from the gitingest redesign) becomes `Agent` + coral `Trace`.
- `README.md`'s prose references to the project's name (not its `git
  clone`/`cd` command examples, which reference the actual repo directory
  name and must stay accurate to what a user actually has on disk).
- `CLAUDE.md`'s prose references to the project's name going forward.

## Product-communication fixes (all in `frontend/src/components/RepoForm.tsx` unless noted)

**1. Step-by-step explainer.** Replaces the current one-line subtitle in
`App.tsx` with 3-4 numbered steps, always visible above the form:
1. Pegá la URL de un repo público de GitHub.
2. Escribí tu pregunta.
3. Mirá en vivo cómo el agente decide qué herramienta usar.
4. Leé la respuesta final.

**2. Python-only notice.** A small, always-visible line next to the repo
URL field (not reactive to a failed/no-index submission — visible before
the user types anything): "Búsqueda semántica disponible solo para repos
Python — otros lenguajes usan exploración directa de archivos."

**3. API-key help copy rewrite.** The existing help text ("Opcional —
solo necesario si tu servidor tiene CODERAG_API_KEY configurada.") is
replaced with copy that actually explains the mechanism, not just that
it's optional: something like "CODERAG_API_KEY es una variable de entorno
opcional que quien corre este backend puede configurar para protegerlo.
Si vos no la configuraste, dejá este campo vacío." The field's
placement/collapsibility (a toggle button, hidden by default) is
unchanged — only the copy changes, per the user's explicit call that the
problem is content, not prominence.

## The two-column live log — the central piece

**Problem this solves:** today, every event (`reasoning`, `tool_call`,
`tool_result`, `indexing_*`, `no_semantic_index`, `answer_token`, `done`,
`error`) renders as one line in one long vertical column
(`EventLogLine`, mapped in sequence by `RunCard`). There's no visual
distinction between "the agent used semantic search here" and "the agent
read/grepped files here" — a user has to read each line's tool name to
tell, and it doesn't register as a clear signal either way.

**New structure**, per `RunCard`:
1. **Status strip** (full width, top): `indexing_start`/`indexing_done`
   and `no_semantic_index` events — unchanged rendering from today
   (`EventLogLine`'s existing cases), just repositioned to their own
   strip above everything else instead of being interleaved into the main
   log.
2. **Reasoning strip** (full width): `reasoning` events — unchanged
   rendering, repositioned above the two columns since reasoning
   precedes and informs both possible tool choices, not one or the other.
3. **Two columns, side by side**: every `tool_call`/`tool_result` event
   pair is routed by its `tool` field — `search_code` goes to the left
   ("RAG") column, `Read`/`Grep`/`Glob` go to the right ("Tools") column.
   Each column renders its events in arrival order using the existing
   `EventLogLine` cases for `tool_call`/`tool_result`, unchanged — only
   the routing/layout is new. **If the RAG column ends a run with zero
   events, that emptiness is itself the signal** that semantic search
   wasn't used for that question — no additional "RAG wasn't used" copy
   needed, the empty column communicates it directly.
4. **Answer** (full width, bottom): the merged, markdown-rendered
   `answer_token` stream — unchanged from today.

**New component:** `frontend/src/components/TwoColumnLog.tsx`, taking
the same `renderItems`-shaped array `RunCard` already builds (or a
lightly adapted version of it) and doing the four-way split described
above, then rendering the status/reasoning strips and the two-column
grid. `RunCard.tsx` is refactored to delegate this rendering to
`TwoColumnLog` instead of its current single `.map()` over
`EventLogLine`. `EventLogLine.tsx` itself is **unchanged** — every event
type still renders exactly as it does today; only which container it
renders inside changes.

**Column headers:** each column gets a small static label ("Búsqueda
semántica" / "Herramientas de archivo" or similar short Spanish labels)
so the split reads clearly even on a run where one column stays empty.

**Per-column agent explanation (why this method was chosen).** Beyond
just showing *that* a column was used, each used column ends with a short
explanation, in the agent's own words, of *why* it chose that approach
for this question — directly addressing "it just looks like an LLM, the
value-add isn't visible" by making the tool-choice reasoning explicit and
attached to the evidence (the actual tool calls above it), not buried in
a general `reasoning` block.

Mechanism (chosen over a second dedicated model call, to avoid extra
latency/cost per question — accepting in exchange that this depends on
the model reliably following an instructed format, which is not
guaranteed, so degradation must be graceful):
`ORCHESTRATOR_SYSTEM_PROMPT` (`coderag_mcp/orchestrator/agents.py`)
gains an instruction: after answering, append one delimited section per
method actually used, using markers chosen specifically to not collide
with Markdown syntax (no `#`, no `---`, which Markdown treats as headings
and thematic breaks respectively):

```
@@AGENTTRACE:RAG@@
<short explanation of why semantic search was the right approach here>
@@AGENTTRACE:TOOLS@@
<short explanation of why direct file exploration was the right approach here>
@@AGENTTRACE:END@@
```

Only sections for methods actually used appear (if the run only used
`search_code`, only the `RAG` section appears, and vice versa).

**Parsing happens entirely on the frontend**, not the backend — the
backend's streamed `answer_token` events are completely unchanged, so
`ask_stream()`/`ask.py` needs no changes beyond the system-prompt
addition. A new pure function, `frontend/src/lib/splitAgentExplanations.ts`
(`splitAgentExplanations(fullAnswerText: string) -> { answer: string;
ragExplanation: string | null; toolsExplanation: string | null }`),
splits the merged final answer text on these markers. This split runs
**once, on `done`** — not incrementally as tokens stream in, since a
marker could itself arrive split across two `answer_token` events and a
naive incremental parse could show/hide content flickering. Before
`done`, the full accumulated text (markers and all, if the model has
started emitting them) renders as-is in the main answer area, same as
today — a bit of raw marker text may be visible for a moment on a fast
connection, which is an accepted, minor, temporary artifact, not a defect
to engineer around.

**Graceful degradation:** if the markers are absent or malformed (the
model didn't follow the instruction, or used a different format despite
being told), `splitAgentExplanations` finds no matches and returns the
full original text as `answer` with both explanations `null` — the
answer displays exactly as it does today, and the columns simply don't
get a trailing explanation. This is a real, accepted possibility, not an
edge case to eliminate — the system prompt is a strong hint, not an
enforced contract.

**Responsive behavior:** on narrow viewports, the two columns should
stack vertically rather than compress unreadably — exact breakpoint
decided at implementation time using this project's existing Tailwind
responsive conventions, not specified further here since it's a
mechanical responsive-design detail, not a product decision.

## Testing

- `TwoColumnLog`: unit tests confirming a `search_code` tool_call/result
  pair renders in the left column, a `Read`/`Grep`/`Glob` pair renders in
  the right column, `reasoning`/`indexing_*`/`no_semantic_index` render
  in the status/reasoning strips (not either column), and `answer_token`
  renders in the full-width answer area. A test confirming an empty RAG
  column (no `search_code` events) renders as a genuinely empty column,
  not a hidden/collapsed one — the emptiness needs to be visible, not
  disappeared.
- `splitAgentExplanations`: unit tests covering both markers present,
  only one marker present, no markers present (graceful degradation —
  full text returned as `answer`, both explanations `null`), and markers
  present but empty sections.
- `RepoForm`: updated/new tests for the step-by-step explainer text, the
  Python-only notice's always-visible presence, and the rewritten
  API-key help copy.
- `App.tsx`: updated test for the new wordmark ("AgentTrace").
- Existing `RunCard`/`EventLogLine` tests that assert on event rendering
  should mostly keep passing unchanged (per the "EventLogLine itself is
  unchanged" decision above) — tests asserting on `RunCard`'s specific
  DOM structure/ordering will need updates to match the new
  strips-plus-columns layout.
- Manual browser verification (per this project's now-established
  practice, reinforced twice today after two incidents of implementers
  under-verifying CSS-visual changes): an actual screenshot or
  computed-style check confirming the two columns render side by side,
  the RAG column is visibly empty on a non-search_code run, and the
  reasoning/status strips sit above them — not just that the DOM contains
  the right elements.
- A backend test confirming `ORCHESTRATOR_SYSTEM_PROMPT` contains the new
  marker-format instruction (a simple string-content assertion — the
  prompt is a plain constant, not executable logic to test more deeply
  than that).
- Full existing test suite (100 backend / 37 frontend at time of writing)
  must stay green; the one backend change (the system-prompt addition) is
  a constant-string change with no behavioral branching, so no existing
  backend test should be affected by it.
