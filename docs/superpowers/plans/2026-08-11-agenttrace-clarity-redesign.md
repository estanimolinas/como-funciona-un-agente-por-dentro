# AgentTrace Clarity Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product to "AgentTrace" (branding only), add a
step-by-step explainer, an always-visible Python-only notice, clearer
API-key copy, and — the central piece — a two-column live event log that
visibly separates semantic-search activity from raw file-tool activity
and lets the agent explain, in its own words, why it chose each method.
Per `docs/superpowers/specs/2026-08-11-agenttrace-clarity-redesign-design.md`.

**Architecture:** Almost entirely frontend. A new pure function,
`splitAgentExplanations()`, parses agent-authored marker text out of the
final answer; a new component, `TwoColumnLog`, routes live events into a
RAG column, a Tools column, and full-width status/reasoning/answer
strips, replacing `RunCard`'s current single linear event list.
`EventLogLine` itself is unchanged — every event still renders through
its existing cases, only the container changes. One backend touch: the
orchestrator's system prompt gains an instruction to emit the marker
format `splitAgentExplanations()` consumes.

**Tech Stack:** React + TypeScript + Tailwind CSS (existing), Python
(existing). No new dependencies.

## Global Constraints

- **Rename scope: user-facing branding only.** The Python package
  (`coderag_mcp/`), its imports, the git repository name, and
  `pyproject.toml`'s project name are unchanged. Only `frontend/index.html`'s
  `<title>`, `frontend/src/App.tsx`'s wordmark, and prose (not file-path)
  mentions of the project's display name in `README.md`/`CLAUDE.md` change.
  Documentation file paths like
  `docs/superpowers/specs/2026-08-08-coderag-mcp-backend-design.md` are
  never renamed — those files exist on disk with those exact names.
- New wordmark: `Agent` + coral (`text-rose-500`) `Trace` — same coloring
  pattern as the current `code`/`rag`/`-mcp` split, just different word
  boundaries.
- Marker format (exact, case-sensitive, chosen specifically to avoid
  colliding with Markdown syntax — no `#`, no `---`):
  ```
  @@AGENTTRACE:RAG@@
  <explanation>
  @@AGENTTRACE:TOOLS@@
  <explanation>
  @@AGENTTRACE:END@@
  ```
  Only sections for methods actually used appear. Parsing happens
  entirely client-side; the backend's only change is instructing the
  model to emit this format — `ask_stream()`'s event shapes are
  completely unchanged.
- Column routing: `tool_call`/`tool_result` events with `tool ===
  'search_code'` go to the RAG (left) column; every other tool name
  (`Read`, `Grep`, `Glob`, or an unexpectedly missing/other value) goes to
  the Tools (right) column. `reasoning`, `indexing_start`, `indexing_done`,
  `no_semantic_index`, and `error` events render in full-width strips
  above the two columns, not inside either column. `done` events render
  nothing (unchanged from `EventLogLine`'s existing behavior). The merged
  `answer_token` stream (after `splitAgentExplanations()` extracts any
  trailing marker sections) renders full-width below the columns.
- `EventLogLine.tsx` is **not modified** by this plan — every event type
  it already handles renders exactly as it does today. `TwoColumnLog` and
  `RunCard` reuse it as-is, including passing synthetic `{ type:
  'answer_token', text: ... }` events to reuse its markdown rendering for
  the main answer and for each column's trailing explanation.
- Full test suite must stay green: **100 backend / 37 frontend** at
  plan-writing time (both will grow — Task 3 adds a backend test, Tasks
  1-2 and 4-6 add/update frontend tests).

---

### Task 1: Rename to AgentTrace (branding only)

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing from later tasks.
- Produces: no interface changes — display text only.

- [ ] **Step 1: Write the failing test**

In `frontend/src/App.test.tsx`, change the wordmark assertion from:

```tsx
    expect(
      screen.getByText((_, element) => element?.tagName.toLowerCase() === 'h1' && element.textContent === 'coderag-mcp'),
    ).toBeInTheDocument()
```

to:

```tsx
    expect(
      screen.getByText((_, element) => element?.tagName.toLowerCase() === 'h1' && element.textContent === 'AgentTrace'),
    ).toBeInTheDocument()
```

(Leave the rest of this test file's assertions — the subtitle/form
checks — for Task 2 to update; don't touch them here.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- App` (in `frontend/`)
Expected: FAIL — the `<h1>`'s combined text content is still `coderag-mcp`.

- [ ] **Step 3: Update the wordmark in `App.tsx`**

In `frontend/src/App.tsx`, change:

```tsx
        <h1 className="text-4xl font-bold tracking-tight">
          code<span className="text-rose-500">rag</span>-mcp
        </h1>
```

to:

```tsx
        <h1 className="text-4xl font-bold tracking-tight">
          Agent<span className="text-rose-500">Trace</span>
        </h1>
```

- [ ] **Step 4: Update the page title**

In `frontend/index.html`, change:

```html
    <title>coderag-mcp</title>
```

to:

```html
    <title>AgentTrace</title>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- App` (in `frontend/`)
Expected: passes (this task's assertion; Task 2 will touch the
subtitle/step-explainer assertions in the same test separately).

- [ ] **Step 6: Update prose mentions in `README.md`**

In `README.md`, change the header line 1 from:

```markdown
# CodeRAG-MCP
```

to:

```markdown
# AgentTrace
```

Do not change anything else in `README.md` in this task — its `git
clone`/`cd` command examples reference the actual repository directory
name (`coderag-mcp`), which is unchanged, and other `coderag_mcp`
mentions are the Python package name, also unchanged.

- [ ] **Step 7: Update prose mentions in `CLAUDE.md`**

In `CLAUDE.md`, change the header line 1 from:

```markdown
# CodeRAG-MCP — context for a fresh Claude session
```

to:

```markdown
# AgentTrace — context for a fresh Claude session
```

Also find the line (search for "coderag-mcp orchestrator") reading:

```markdown
  coderag-mcp orchestrator, consuming `POST /ask/stream` to show a live
```

and change `coderag-mcp orchestrator` to `AgentTrace orchestrator` (keep
the rest of that sentence/paragraph unchanged). Do not change any
`docs/superpowers/...` file-path references anywhere in this file — those
are real file names on disk.

- [ ] **Step 8: Run the full frontend test suite**

Run: `npm test` (in `frontend/`)
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/index.html frontend/src/App.tsx frontend/src/App.test.tsx README.md CLAUDE.md
git commit -m "feat(frontend): rename product branding from coderag-mcp to AgentTrace"
```

---

### Task 2: Step-by-step explainer, Python-only notice, API-key copy rewrite

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/components/RepoForm.tsx`
- Modify: `frontend/src/components/RepoForm.test.tsx`

**Interfaces:**
- Consumes: nothing from Task 1 beyond the already-renamed wordmark (this
  task edits adjacent, non-overlapping regions of the same two files).
- Produces: no interface changes — copy and one new always-visible
  paragraph in `RepoForm`.

- [ ] **Step 1: Write the failing test for the step-by-step explainer**

In `frontend/src/App.test.tsx`, replace the subtitle assertion:

```tsx
    expect(screen.getByText(/mirá en vivo cómo el agente explora el código/i)).toBeInTheDocument()
```

with:

```tsx
    expect(screen.getByText(/pegá la url de un repo público/i)).toBeInTheDocument()
    expect(screen.getByText(/leé la respuesta final/i)).toBeInTheDocument()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- App` (in `frontend/`)
Expected: FAIL — the subtitle paragraph doesn't contain this text yet.

- [ ] **Step 3: Replace the subtitle with a numbered step list**

In `frontend/src/App.tsx`, change:

```tsx
        <p className="text-slate-400">
          Mirá en vivo cómo el agente explora el código para responder.
        </p>
```

to:

```tsx
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-400">
          <li>Pegá la URL de un repo público de GitHub.</li>
          <li>Escribí tu pregunta.</li>
          <li>Mirá en vivo cómo el agente decide qué herramienta usar.</li>
          <li>Leé la respuesta final.</li>
        </ol>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- App` (in `frontend/`)
Expected: passes.

- [ ] **Step 5: Write the failing test for the Python-only notice**

Add to `frontend/src/components/RepoForm.test.tsx` (inside the existing
`describe('RepoForm', ...)` block):

```tsx
  it('always shows a note that semantic search only applies to Python repos', () => {
    render(<RepoForm onSubmit={vi.fn()} />)
    expect(screen.getByText(/solo para repos python/i)).toBeInTheDocument()
  })
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `npm test -- RepoForm` (in `frontend/`)
Expected: FAIL — no element matches `/solo para repos python/i` yet.

- [ ] **Step 7: Add the Python-only notice**

In `frontend/src/components/RepoForm.tsx`, find the repo URL `<label>`
block:

```tsx
        <label className="flex flex-col gap-1">
          <span>URL del repo</span>
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
          />
        </label>
```

and add a paragraph immediately after its closing `</label>` (still
before the `Pregunta` label):

```tsx
        <label className="flex flex-col gap-1">
          <span>URL del repo</span>
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
          />
        </label>
        <p className="text-xs text-slate-500">
          Búsqueda semántica disponible solo para repos Python — otros
          lenguajes usan exploración directa de archivos.
        </p>
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `npm test -- RepoForm` (in `frontend/`)
Expected: passes.

- [ ] **Step 9: Update the API-key help copy test**

Find the existing test in `frontend/src/components/RepoForm.test.tsx`
named `'shows an always-visible explanation when the API key field is
expanded'`. It currently asserts:

```tsx
    expect(screen.getByText(/opcional.*CODERAG_API_KEY.*configurada/i)).toBeInTheDocument()
```

Change this assertion to:

```tsx
    expect(screen.getByText(/CODERAG_API_KEY/)).toBeInTheDocument()
    expect(screen.getByText(/dejá este campo vacío/i)).toBeInTheDocument()
```

- [ ] **Step 10: Run the test to verify it fails**

Run: `npm test -- RepoForm` (in `frontend/`)
Expected: FAIL — the current copy doesn't contain "dejá este campo vacío".

- [ ] **Step 11: Rewrite the API-key help copy**

In `frontend/src/components/RepoForm.tsx`, change:

```tsx
            <p className="text-xs text-slate-400">
              Opcional — solo necesario si tu servidor tiene CODERAG_API_KEY configurada.
            </p>
```

to:

```tsx
            <p className="text-xs text-slate-400">
              CODERAG_API_KEY es una variable de entorno opcional que quien
              corre este backend puede configurar para protegerlo. Si vos
              no la configuraste, dejá este campo vacío.
            </p>
```

- [ ] **Step 12: Run the full frontend test suite**

Run: `npm test` (in `frontend/`)
Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/components/RepoForm.tsx frontend/src/components/RepoForm.test.tsx
git commit -m "feat(frontend): add step-by-step explainer, Python-only notice, clearer API-key copy"
```

---

### Task 3: Backend — system-prompt instruction for method-explanation markers

**Files:**
- Modify: `coderag_mcp/orchestrator/agents.py`
- Test: `tests/orchestrator/test_agents.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (independent backend change).
- Produces: no new function/type — `ORCHESTRATOR_SYSTEM_PROMPT`'s content
  changes (still a plain string constant, same import path used by
  `orchestrator/ask.py`, unaffected signature). Task 4's frontend
  `splitAgentExplanations()` is written independently against the exact
  marker format specified in the Global Constraints section above, not
  against this task's output directly — the two are connected only by
  both following that shared, spec-defined format.

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestrator/test_agents.py` (append to the existing file,
alongside its current `test_system_prompt_mentions_both_tool_families`):

```python
def test_system_prompt_instructs_the_agent_to_emit_method_explanation_markers():
    assert "@@AGENTTRACE:RAG@@" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "@@AGENTTRACE:TOOLS@@" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "@@AGENTTRACE:END@@" in ORCHESTRATOR_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/orchestrator/test_agents.py -v`
Expected: FAIL — `ORCHESTRATOR_SYSTEM_PROMPT` doesn't contain these
markers yet.

- [ ] **Step 3: Extend the system prompt**

In `coderag_mcp/orchestrator/agents.py`, change:

```python
ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are a code question-answering assistant with two ways to find information "
    "in this repository:\n"
    "- search_code: semantic search over pre-indexed code chunks. Use this for "
    "conceptual questions ('how does X work', 'where is X handled') where matching "
    "the meaning of the question matters more than exact wording.\n"
    "- Read, Grep, Glob: exact search and file reading over the real, current "
    "repository files. Use this for structural or exact-location questions where "
    "precise, up-to-date file:line accuracy matters more than semantic similarity.\n"
    "Choose per question - don't default to only one. Always cite file:line for "
    "anything you reference."
)
```

to:

```python
ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are a code question-answering assistant with two ways to find information "
    "in this repository:\n"
    "- search_code: semantic search over pre-indexed code chunks. Use this for "
    "conceptual questions ('how does X work', 'where is X handled') where matching "
    "the meaning of the question matters more than exact wording.\n"
    "- Read, Grep, Glob: exact search and file reading over the real, current "
    "repository files. Use this for structural or exact-location questions where "
    "precise, up-to-date file:line accuracy matters more than semantic similarity.\n"
    "Choose per question - don't default to only one. Always cite file:line for "
    "anything you reference.\n"
    "\n"
    "After your answer, append one short section per method you actually used, in "
    "this exact format (these markers must not be inside a code block or otherwise "
    "escaped, and must not use Markdown syntax like '#' or '---'):\n"
    "\n"
    "@@AGENTTRACE:RAG@@\n"
    "<if you used search_code: one sentence on why semantic search was the right "
    "approach for this question>\n"
    "@@AGENTTRACE:TOOLS@@\n"
    "<if you used Read, Grep, or Glob: one sentence on why direct file exploration "
    "was the right approach for this question>\n"
    "@@AGENTTRACE:END@@\n"
    "\n"
    "Only include the @@AGENTTRACE:RAG@@ section if you actually called search_code, "
    "and only include the @@AGENTTRACE:TOOLS@@ section if you actually called Read, "
    "Grep, or Glob. If you only used one method, include only that one section "
    "(still end with @@AGENTTRACE:END@@)."
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/orchestrator/test_agents.py -v`
Expected: passes.

- [ ] **Step 5: Run the full backend suite**

Run: `./.venv/bin/pytest -q`
Expected: all tests pass, no regressions — this is a constant-string
change with no behavioral branching, so no existing test should be
affected.

- [ ] **Step 6: Commit**

```bash
git add coderag_mcp/orchestrator/agents.py tests/orchestrator/test_agents.py
git commit -m "feat(backend): instruct the orchestrator to explain its method choice via AGENTTRACE markers"
```

---

### Task 4: `splitAgentExplanations()` — pure marker-parsing function

**Files:**
- Create: `frontend/src/lib/splitAgentExplanations.ts`
- Test: `frontend/src/lib/splitAgentExplanations.test.ts`

**Interfaces:**
- Produces (used by Task 5): `splitAgentExplanations(fullAnswerText:
  string) -> { answer: string; ragExplanation: string | null;
  toolsExplanation: string | null }`, exported from
  `frontend/src/lib/splitAgentExplanations.ts`. Graceful degradation: if
  the `@@AGENTTRACE:END@@` marker is absent, or neither
  `@@AGENTTRACE:RAG@@` nor `@@AGENTTRACE:TOOLS@@` is present, returns
  `{ answer: fullAnswerText, ragExplanation: null, toolsExplanation: null }`
  unchanged.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/splitAgentExplanations.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import { splitAgentExplanations } from './splitAgentExplanations'

describe('splitAgentExplanations', () => {
  it('splits out both explanations when both markers are present', () => {
    const text =
      'La respuesta.\n' +
      '@@AGENTTRACE:RAG@@\n' +
      'Expliqué RAG.\n' +
      '@@AGENTTRACE:TOOLS@@\n' +
      'Expliqué tools.\n' +
      '@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe('La respuesta.')
    expect(result.ragExplanation).toBe('Expliqué RAG.')
    expect(result.toolsExplanation).toBe('Expliqué tools.')
  })

  it('splits out only the RAG explanation when only that marker is present', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:RAG@@\nExpliqué RAG.\n@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe('La respuesta.')
    expect(result.ragExplanation).toBe('Expliqué RAG.')
    expect(result.toolsExplanation).toBeNull()
  })

  it('splits out only the tools explanation when only that marker is present', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:TOOLS@@\nExpliqué tools.\n@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe('La respuesta.')
    expect(result.ragExplanation).toBeNull()
    expect(result.toolsExplanation).toBe('Expliqué tools.')
  })

  it('returns the full text as the answer with no explanations when no markers are present', () => {
    const text = 'Solo una respuesta normal, sin marcadores.'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe(text)
    expect(result.ragExplanation).toBeNull()
    expect(result.toolsExplanation).toBeNull()
  })

  it('treats an empty explanation section as null rather than an empty string', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:RAG@@\n\n@@AGENTTRACE:END@@'
    const result = splitAgentExplanations(text)
    expect(result.ragExplanation).toBeNull()
  })

  it('does not split when the END marker is missing (incomplete/partial marker text)', () => {
    const text = 'La respuesta.\n@@AGENTTRACE:RAG@@\nTodavía escribiendo'
    const result = splitAgentExplanations(text)
    expect(result.answer).toBe(text)
    expect(result.ragExplanation).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- splitAgentExplanations` (in `frontend/`)
Expected: FAIL — the module doesn't exist yet.

- [ ] **Step 3: Implement `splitAgentExplanations`**

Create `frontend/src/lib/splitAgentExplanations.ts`:

```typescript
export interface AgentExplanations {
  answer: string
  ragExplanation: string | null
  toolsExplanation: string | null
}

const RAG_MARKER = '@@AGENTTRACE:RAG@@'
const TOOLS_MARKER = '@@AGENTTRACE:TOOLS@@'
const END_MARKER = '@@AGENTTRACE:END@@'

export function splitAgentExplanations(fullAnswerText: string): AgentExplanations {
  const ragIndex = fullAnswerText.indexOf(RAG_MARKER)
  const toolsIndex = fullAnswerText.indexOf(TOOLS_MARKER)
  const endIndex = fullAnswerText.indexOf(END_MARKER)

  if (endIndex === -1 || (ragIndex === -1 && toolsIndex === -1)) {
    return { answer: fullAnswerText, ragExplanation: null, toolsExplanation: null }
  }

  const markerIndices = [ragIndex, toolsIndex].filter((i) => i !== -1).sort((a, b) => a - b)
  const answer = fullAnswerText.slice(0, markerIndices[0]).trim()

  let ragExplanation: string | null = null
  let toolsExplanation: string | null = null

  if (ragIndex !== -1) {
    const ragEnd = toolsIndex !== -1 && toolsIndex > ragIndex ? toolsIndex : endIndex
    ragExplanation = fullAnswerText.slice(ragIndex + RAG_MARKER.length, ragEnd).trim() || null
  }

  if (toolsIndex !== -1) {
    const toolsEnd = ragIndex !== -1 && ragIndex > toolsIndex ? ragIndex : endIndex
    toolsExplanation = fullAnswerText.slice(toolsIndex + TOOLS_MARKER.length, toolsEnd).trim() || null
  }

  return { answer, ragExplanation, toolsExplanation }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- splitAgentExplanations` (in `frontend/`)
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/splitAgentExplanations.ts frontend/src/lib/splitAgentExplanations.test.ts
git commit -m "feat(frontend): add splitAgentExplanations() to parse per-method AGENTTRACE markers"
```

---

### Task 5: `TwoColumnLog` — the two-column live event display

**Files:**
- Create: `frontend/src/components/TwoColumnLog.tsx`
- Test: `frontend/src/components/TwoColumnLog.test.tsx`

**Interfaces:**
- Consumes: `splitAgentExplanations` from Task 4
  (`frontend/src/lib/splitAgentExplanations.ts`), `EventLogLine` from
  `frontend/src/components/EventLogLine.tsx` (unchanged, imported as-is),
  `StreamEvent`/`RunStatus` from `frontend/src/types.ts` (unchanged).
- Produces (used by Task 6): `TwoColumnLog(props: { events: StreamEvent[];
  status: RunStatus; isTruncated: boolean }) -> JSX.Element`, exported
  from `frontend/src/components/TwoColumnLog.tsx`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/TwoColumnLog.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TwoColumnLog } from './TwoColumnLog'
import type { StreamEvent } from '../types'

describe('TwoColumnLog', () => {
  it('routes a search_code tool_call/result pair into the RAG column', () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'search_code', input: { query: 'auth' } },
      {
        type: 'tool_result',
        tool: 'search_code',
        tool_use_id: 'toolu_1',
        output_preview: 'found it',
        is_error: false,
      },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(screen.getByText(/search_code/)).toBeInTheDocument()
    expect(screen.getByText(/found it/)).toBeInTheDocument()
  })

  it('routes a Read/Grep/Glob tool_call/result pair into the Tools column', () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'Grep', input: { pattern: 'foo' } },
      {
        type: 'tool_result',
        tool: 'Grep',
        tool_use_id: 'toolu_2',
        output_preview: 'main.py:3:foo',
        is_error: false,
      },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(screen.getByText(/Grep/)).toBeInTheDocument()
    expect(screen.getByText(/main\.py:3:foo/)).toBeInTheDocument()
  })

  it('renders reasoning, indexing, and no_semantic_index events outside either column', () => {
    const events: StreamEvent[] = [
      { type: 'reasoning', text: 'Thinking about the approach.' },
      { type: 'indexing_done', chunk_count: 5, duration_s: 1.2 },
      { type: 'no_semantic_index', message: 'Sin indice para este repo.' },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(screen.getByText(/Thinking about the approach/)).toBeInTheDocument()
    expect(screen.getByText(/Indexado 5 chunks/)).toBeInTheDocument()
    expect(screen.getByText(/Sin indice para este repo/)).toBeInTheDocument()
  })

  it('renders the merged answer in a full-width area', async () => {
    const events: StreamEvent[] = [
      { type: 'answer_token', text: 'La respuesta es ' },
      { type: 'answer_token', text: 'cuarenta y dos.' },
    ]
    render(<TwoColumnLog events={events} status="streaming" isTruncated={false} />)
    expect(await screen.findByText('La respuesta es cuarenta y dos.')).toBeInTheDocument()
  })

  it('leaves the RAG column visibly present but empty when no search_code events occurred', () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'Read', input: { file_path: 'main.py' } },
      {
        type: 'tool_result',
        tool: 'Read',
        tool_use_id: 'toolu_3',
        output_preview: 'print("hi")',
        is_error: false,
      },
    ]
    const { container } = render(
      <TwoColumnLog events={events} status="streaming" isTruncated={false} />,
    )
    expect(screen.queryByText(/search_code/)).not.toBeInTheDocument()
    expect(screen.getByText(/búsqueda semántica/i)).toBeInTheDocument()
    expect(container.textContent).toContain('Herramientas de archivo')
  })

  it('renders a per-column agent explanation when markers are present in the answer', async () => {
    const events: StreamEvent[] = [
      { type: 'tool_call', tool: 'search_code', input: { query: 'auth' } },
      {
        type: 'tool_result',
        tool: 'search_code',
        tool_use_id: 'toolu_1',
        output_preview: 'found it',
        is_error: false,
      },
      {
        type: 'answer_token',
        text:
          'Auth se maneja en auth.py.\n' +
          '@@AGENTTRACE:RAG@@\n' +
          'Usé búsqueda semántica porque la pregunta era conceptual.\n' +
          '@@AGENTTRACE:END@@',
      },
    ]
    render(<TwoColumnLog events={events} status="done" isTruncated={false} />)
    expect(
      await screen.findByText(/Usé búsqueda semántica porque la pregunta era conceptual/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Auth se maneja en auth\.py/)).toBeInTheDocument()
    expect(screen.queryByText(/@@AGENTTRACE/)).not.toBeInTheDocument()
  })

  it('shows a connecting status line while status is connecting', () => {
    render(<TwoColumnLog events={[]} status="connecting" isTruncated={false} />)
    expect(screen.getByText(/conectando/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- TwoColumnLog` (in `frontend/`)
Expected: FAIL — the module doesn't exist yet.

- [ ] **Step 3: Implement `TwoColumnLog`**

Create `frontend/src/components/TwoColumnLog.tsx`:

```tsx
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- TwoColumnLog` (in `frontend/`)
Expected: all pass.

- [ ] **Step 5: Run the full frontend test suite**

Run: `npm test` (in `frontend/`)
Expected: all tests pass (Task 6 hasn't wired `TwoColumnLog` into
`RunCard` yet, so nothing else should be affected by this task alone).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/TwoColumnLog.tsx frontend/src/components/TwoColumnLog.test.tsx
git commit -m "feat(frontend): add TwoColumnLog, routing live events into RAG/Tools columns"
```

---

### Task 6: `RunCard` — delegate to `TwoColumnLog`

**Files:**
- Modify: `frontend/src/components/RunCard.tsx`
- Modify: `frontend/src/components/RunCard.test.tsx`

**Interfaces:**
- Consumes: `TwoColumnLog` from Task 5 (`import { TwoColumnLog } from
  './TwoColumnLog'`).
- Produces: no interface changes — `RunCard`'s props contract
  (`{ repoUrl, question, apiKey }`) is unchanged; only its internal
  rendering delegates to `TwoColumnLog` instead of its current inline
  `renderItems`/`.map()` logic.

- [ ] **Step 1: Read the current `RunCard.test.tsx` to confirm what must
  keep passing**

Before making any change, read `frontend/src/components/RunCard.test.tsx`
in full. It has 3 existing tests (header text, merged-answer text,
truncated-answer marker) — this task's refactor must keep all 3 passing
unchanged, since none of them depend on the old `renderItems` merging
logic specifically, only on the final rendered text. No new test is
strictly required for this task (the routing/explanation behavior is
already covered by Task 5's `TwoColumnLog.test.tsx`, which tests it in
isolation) — this task's job is the refactor itself, verified by the 3
existing tests still passing.

- [ ] **Step 2: Refactor `RunCard.tsx` to delegate to `TwoColumnLog`**

Replace the entire contents of `frontend/src/components/RunCard.tsx`:

```tsx
import { useMemo } from 'react'

import { useAskStream } from '../hooks/useAskStream'
import { OffsetCard } from './OffsetCard'
import { TwoColumnLog } from './TwoColumnLog'
import type { AskStreamParams } from '../types'

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

  return (
    <OffsetCard className="p-4">
      <div className="mb-2 text-sm text-slate-400">
        {repoUrl} — {question}
      </div>
      <p className="mb-2 text-xs text-slate-400">Así explora y responde el agente, en vivo:</p>
      <TwoColumnLog events={events} status={status} isTruncated={isTruncated} />
    </OffsetCard>
  )
}
```

This removes the old `renderItems`/`pendingAnswer` merge loop and the
direct `EventLogLine` import/mapping — that logic now lives inside
`TwoColumnLog` (Task 5), which computes the full merged answer text and
routes every other event type by category.

- [ ] **Step 3: Run the existing `RunCard` tests to verify they still pass**

Run: `npm test -- RunCard` (in `frontend/`)
Expected: all 3 existing tests pass unchanged. If any fails, read the
actual rendered output before changing the test — a failure here means
the refactor changed observable behavior, which this task should not do;
fix `RunCard.tsx`/`TwoColumnLog.tsx`, not the test.

- [ ] **Step 4: Run the full frontend test suite**

Run: `npm test` (in `frontend/`)
Expected: all tests pass.

- [ ] **Step 5: Manually verify in the browser**

With the backend running (`./.venv/bin/uvicorn coderag_mcp.api.main:app
--port 8000` from the repo root) and the frontend dev server running
(`npm run dev` in `frontend/`), submit the `pypa/sampleproject` example
question and confirm: the RAG column shows `search_code` activity, the
Tools column shows any `Read`/`Grep`/`Glob` activity (or stays visibly
empty if none occurred), the final answer renders full-width below, and
if the model followed the new marker instruction, a short explanation
appears at the bottom of whichever column(s) were used. Take an actual
screenshot (Playwright, if available, per this project's now-established
practice of verifying CSS/layout changes with a real rendered check, not
just DOM presence) rather than only checking DOM presence — this is a
real layout restructuring, the kind of change that has previously looked
correct in source but rendered wrong. Note exactly what you observed in
your task report.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RunCard.tsx frontend/src/components/RunCard.test.tsx
git commit -m "feat(frontend): wire RunCard to render the live log via TwoColumnLog"
```

---

## Final check

After Task 6, run `./.venv/bin/pytest -q` once more from the repo root
and `npm test` once more from `frontend/`, and confirm both suites pass
(101 backend — 100 pre-existing + 1 new from Task 3 — and 37 pre-existing
+ 1 App test extension (not a new test) + 1 RepoForm test (Task 2) + 6
TwoColumnLog tests (Task 5) + 6 splitAgentExplanations tests (Task 4) =
50 frontend, though verify the actual final counts rather than trusting
this arithmetic) before moving to
`superpowers:finishing-a-development-branch`.
