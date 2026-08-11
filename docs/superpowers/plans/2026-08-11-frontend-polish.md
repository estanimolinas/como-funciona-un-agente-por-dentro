# Frontend Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface a "no semantic index" signal for non-Python repos, render
the final answer as real markdown, color-code the agent's reasoning
distinctly, clean up the event log's visual density, and translate the UI
to Spanish, per `docs/superpowers/specs/2026-08-11-frontend-polish-design.md`.

**Architecture:** One new `StreamEvent` variant (`no_semantic_index`),
computed once inside `orchestrator/ask.py`'s `ask_stream()` — the single
function `POST /ask/stream`, `POST /ask`, and the `ask_repo` MCP tool all
flow through — so every caller gets the improved system-prompt guidance
and (for the streaming path) the new event, with zero route-level
duplication. On the frontend: a markdown renderer for the answer bubble,
a recolored `reasoning` case, general `EventLogLine`/`RunCard` visual
cleanup, and a final mechanical Spanish-copy pass across every
user-visible string.

**Tech Stack:** `react-markdown` (new frontend dependency), existing
`coderag_mcp.store.chunks.count_chunks`/`coderag_mcp.store.db.run_db_sync`
(backend, both already exist and are used elsewhere), Tailwind CSS
(existing).

## Global Constraints

- `ask_stream()`'s existing signature and external behavior for repos
  **with** a semantic index are unchanged — this only adds a new code path
  for the zero-chunk case, it doesn't touch the non-zero case.
- The zero-chunk check lives inside `orchestrator/ask.py`'s `ask_stream()`
  (not the route) so `POST /ask`, `POST /ask/stream`, and the `ask_repo`
  MCP tool all benefit — see the design spec's "Where the check belongs"
  rationale.
- New event shape (exact, from the spec): `{"type": "no_semantic_index",
  "message": "This repository has no indexed code (unsupported language,
  or an empty/non-code repo) — answering by exploring files directly
  instead of semantic search."}`. This event is yielded once, before the
  `query()` loop starts, only when `count_chunks(conn, repo_id) == 0`.
- `search_code` stays in `allowed_tools` unconditionally — the fix is a
  system-prompt note, not tool removal.
- `react-markdown` current version at plan-writing time (verified via
  `npm view react-markdown version`): `10.1.0`, peer deps `react >=18` /
  `@types/react >=18` (compatible with this project's `react@^19.2.8`). No
  remark/rehype plugins — default GFM-less renderer is sufficient (no
  tables/footnotes needed).
- Tailwind color additions: `no_semantic_index` uses `text-amber-400`
  (distinct shade from the existing `text-amber-500` `[incomplete]`
  marker, so the two amber uses are visually distinguishable from each
  other while both reading as "attention"); `reasoning` changes from
  `text-slate-500` to `text-violet-400` (unused by any other event type:
  `tool_call` is sky, `tool_result` is emerald/red, `error` is red).
- Spanish-copy pass (Task 5) is a **mechanical string replacement only** —
  no i18n library, no behavior change. Every test selector that currently
  matches an English string (see Task 5's exact list) must be updated in
  the same commit as the string it targets, or the suite breaks.
- LLM-generated text (the answer itself, `reasoning` event text) is never
  translated — only static UI copy this project authors is in scope.
- Full test suite must stay green after every task: **97 backend / 27
  frontend** at plan-writing time (both counts will grow as tasks add
  tests — check the actual current count if it differs when you start).

---

### Task 1: Backend — `no_semantic_index` event + system-prompt note

**Files:**
- Modify: `coderag_mcp/orchestrator/ask.py`
- Test: `tests/orchestrator/test_ask.py`

**Interfaces:**
- Consumes: `coderag_mcp.store.chunks.count_chunks(conn, repo_id) -> int`
  (already exists, already used by `api/ask_stream_route.py`) and
  `coderag_mcp.store.db.run_db_sync(fn, *args, **kwargs)` (already
  exists, same import path).
- Produces: `ask_stream()` now yields an extra `{"type":
  "no_semantic_index", "message": "..."}` event, exactly once, as the
  first event of any call where `count_chunks(conn, repo_id) == 0` —
  before any `tool_call`/`tool_result`/`reasoning`/`answer_token`/`done`
  events. No signature change to `ask_stream()` or `ask()`. Task 2
  consumes this new event `type` in the frontend's `StreamEvent` union.

- [ ] **Step 1: Write the failing test for the zero-chunk path**

Add to `tests/orchestrator/test_ask.py` (below the existing
`_fake_query_stream`/tests, following the same `with (patch(...), ...)`
pattern already used throughout this file):

```python
async def _reasoning_capturing_query_stream(*, prompt, options):
    # Captures the system prompt actually passed to query() so the test can
    # assert on the appended no-index note, then yields a trivial answer.
    _reasoning_capturing_query_stream.captured_system_prompt = options.system_prompt
    yield AssistantMessage(content=[TextBlock(text="No index available here.")], model="test")


@pytest.mark.asyncio
async def test_ask_stream_yields_no_semantic_index_event_when_zero_chunks(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=0) as mock_count,
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_reasoning_capturing_query_stream),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="q")
        ]

    mock_count.assert_called_once_with(conn, 1)
    assert events[0] == {
        "type": "no_semantic_index",
        "message": (
            "This repository has no indexed code (unsupported language, or an "
            "empty/non-code repo) — answering by exploring files directly instead "
            "of semantic search."
        ),
    }
    assert "no indexed code" in _reasoning_capturing_query_stream.captured_system_prompt
    assert "search_code" in _reasoning_capturing_query_stream.captured_system_prompt


@pytest.mark.asyncio
async def test_ask_stream_omits_no_semantic_index_event_when_chunks_exist(tmp_path):
    conn = MagicMock()

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=42),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_reasoning_capturing_query_stream),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="q")
        ]

    assert all(event["type"] != "no_semantic_index" for event in events)
    assert "no indexed code" not in _reasoning_capturing_query_stream.captured_system_prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py -v`
Expected: the two new tests FAIL — `count_chunks` isn't imported/called in
`ask.py` yet, so `patch("coderag_mcp.orchestrator.ask.count_chunks", ...)`
raises `AttributeError: <module> does not have the attribute 'count_chunks'`.

- [ ] **Step 3: Add the imports and the zero-chunk check to `ask_stream()`**

In `coderag_mcp/orchestrator/ask.py`, add two imports near the top
(alongside the existing `from coderag_mcp.indexing import clone` and
`from coderag_mcp.orchestrator.agents import ORCHESTRATOR_SYSTEM_PROMPT`
lines):

```python
from coderag_mcp.store.chunks import count_chunks
from coderag_mcp.store.db import run_db_sync
```

Then, inside `ask_stream()`, right after the `search_server =
build_search_server(conn, repo_id)` line and before the `repo_dir =
await asyncio.to_thread(clone.clone_repo, ...)` line, insert:

```python
    chunk_count = await run_db_sync(count_chunks, conn, repo_id)
    has_semantic_index = chunk_count > 0
    if not has_semantic_index:
        yield {
            "type": "no_semantic_index",
            "message": (
                "This repository has no indexed code (unsupported language, or an "
                "empty/non-code repo) — answering by exploring files directly instead "
                "of semantic search."
            ),
        }
```

Then change the `system_prompt` line inside the `ClaudeAgentOptions(...)`
construction from:

```python
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
```

to:

```python
            system_prompt=(
                ORCHESTRATOR_SYSTEM_PROMPT
                if has_semantic_index
                else ORCHESTRATOR_SYSTEM_PROMPT
                + "\n\nNote: this repository has no indexed code (unsupported "
                "language, or an empty/non-code repo) — search_code will return no "
                "useful results here. Rely on Read, Grep, and Glob instead."
            ),
```

- [ ] **Step 4: Update the 5 existing tests to patch `count_chunks`**

Every existing test in `tests/orchestrator/test_ask.py` that patches
`coderag_mcp.orchestrator.ask.build_search_server`/`clone.clone_repo`/
`clone.cleanup_clone`/`query` (all 5 of them —
`test_ask_concatenates_streamed_text_and_scopes_cwd`,
`test_ask_raises_timeout_error_if_query_never_completes`,
`test_ask_stream_yields_one_event_per_block`,
`test_ask_stream_truncates_long_tool_results`,
`test_ask_stream_raises_timeout_error_if_query_never_completes`) now
exercises the new `count_chunks` call, which on an unpatched `MagicMock()`
`conn` would return an unconfigured `MagicMock` instead of an int and
break the `chunk_count > 0` comparison. Add one line to each test's
`with (...)` block:

```python
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=5),
```

Place it anywhere inside the existing `with (...)` tuple in each of the 5
tests (position doesn't matter, `patch` context managers in a `with`
tuple don't depend on order relative to each other here). This keeps
`has_semantic_index` `True` for all 5, preserving their existing
assertions unchanged — none of them assert on `system_prompt` content or
expect a `no_semantic_index` event, so no other change is needed in
these 5 tests.

- [ ] **Step 5: Run the full test file to verify everything passes**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py -v`
Expected: all tests pass (5 pre-existing + 2 new = 7).

- [ ] **Step 6: Run the full backend suite**

Run: `./.venv/bin/pytest -q`
Expected: all tests pass, no regressions elsewhere.

- [ ] **Step 7: Commit**

```bash
git add coderag_mcp/orchestrator/ask.py tests/orchestrator/test_ask.py
git commit -m "feat(backend): surface a no_semantic_index event and system-prompt note for zero-chunk repos"
```

---

### Task 2: Frontend — `no_semantic_index` type + rendering

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/EventLogLine.tsx`
- Modify: `frontend/src/components/EventLogLine.test.tsx`

**Interfaces:**
- Consumes: the exact event shape from Task 1 —
  `{"type": "no_semantic_index", "message": string}`.
- Produces: `StreamEvent`'s union gains this variant; `EventLogLine`
  handles it in its `switch`. No other component needs to change — this
  event flows through `useAskStream` (generic over `StreamEvent`, no
  special-casing needed there — confirmed by reading its current source,
  it only branches on `'done'`/`'error'`) and `RunCard` (which only
  special-cases `'answer_token'` for merging; every other event type,
  including this new one, already passes straight through to
  `EventLogLine` unchanged).

- [ ] **Step 1: Add the new variant to `types.ts`**

In `frontend/src/types.ts`, add one line to the `StreamEvent` union
(anywhere in the list — order doesn't matter for a TypeScript union type):

```typescript
  | { type: 'no_semantic_index'; message: string }
```

- [ ] **Step 2: Write the failing test**

Add to `frontend/src/components/EventLogLine.test.tsx`:

```tsx
  it('renders a no_semantic_index event', () => {
    render(
      <EventLogLine
        event={{ type: 'no_semantic_index', message: 'No index available here.' }}
      />,
    )
    expect(screen.getByText(/No index available here\./)).toBeInTheDocument()
  })
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `EventLogLine`'s `switch` has no `'no_semantic_index'`
case, so TypeScript's control flow falls through to `undefined` and the
component renders nothing, failing the `getByText` assertion. (Note: this
project's `EventLogLine` switch has no exhaustiveness guard — a missing
case does not fail `tsc`, only this render test catches it. This is a
known, already-deferred minor finding from the original frontend plan;
out of scope to fix here.)

- [ ] **Step 4: Add the case to `EventLogLine.tsx`**

In `frontend/src/components/EventLogLine.tsx`, add a new case to the
`switch` (place it near `indexing_done`, since it's conceptually part of
the "what happened during setup" group):

```tsx
    case 'no_semantic_index':
      return <div className="text-amber-400">⚠ {event.message}</div>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm test`
Expected: all tests pass, including the new one.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/components/EventLogLine.tsx frontend/src/components/EventLogLine.test.tsx
git commit -m "feat(frontend): render the no_semantic_index event"
```

---

### Task 3: Frontend — real markdown rendering for the final answer

**Files:**
- Modify: `frontend/package.json` (new dependency)
- Modify: `frontend/src/components/EventLogLine.tsx`
- Modify: `frontend/src/components/EventLogLine.test.tsx`

**Interfaces:**
- Consumes: nothing new from earlier tasks in this plan.
- Produces: `EventLogLine`'s `'answer_token'` case renders its `event.text`
  through `react-markdown` instead of as plain text, wrapped in a `<div>`
  instead of the current `<span>` (react-markdown's default output is a
  block-level `<p>`, and this component's parent container in `RunCard`
  is a `flex flex-col` list where each event is already its own row — a
  `<div>` fits that layout better than a `<span>`). The `isTruncatedAnswer`
  `[incomplete]` marker stays a separate sibling element, appended after
  the rendered markdown, not inside the markdown source string (avoids any
  markdown-escaping edge cases from splicing plain text into markdown).

- [ ] **Step 1: Install `react-markdown`**

Run (in `frontend/`, using the same npm cache workaround this project's
established practice uses if the default cache has permission issues —
try the plain command first):

```bash
npm install react-markdown
```

If this fails with an `EACCES`/cache permission error (a known
pre-existing environment issue in this project, unrelated to this
package), retry with:

```bash
npm install react-markdown --cache=/tmp/npm-cache
```

Confirm `frontend/package.json`'s `dependencies` now lists
`"react-markdown"` at `^10.x` (verify the actual installed version with
`npm view react-markdown version` if you want to double check what
landed — `10.1.0` was current at plan-writing time, a newer patch/minor
by the time this task runs is fine, a major version bump is not — stop
and flag it if `npm install react-markdown` pulls a `11.x` or higher,
since this plan's usage (`<ReactMarkdown>{text}</ReactMarkdown>`, no
plugins) is written against v10's default export API).

- [ ] **Step 2: Write the failing test**

Add to `frontend/src/components/EventLogLine.test.tsx` (this replaces
the need to change the existing plain-text `'renders an answer_token'`
test — that test's assertion `screen.getByText(/Auth is/)` still passes
unchanged against markdown-rendered output, since react-markdown wraps
plain text with no special syntax in a single `<p>` whose text content is
still `"Auth is "`; leave that existing test as-is and add a new one
specifically proving markdown syntax gets rendered, not shown raw):

```tsx
  it('renders markdown syntax in an answer_token as real formatting, not raw text', () => {
    const { container } = render(
      <EventLogLine event={{ type: 'answer_token', text: 'This is **bold** text.' }} />,
    )
    expect(container.querySelector('strong')).toHaveTextContent('bold')
    expect(screen.queryByText(/\*\*bold\*\*/)).not.toBeInTheDocument()
  })
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — no `<strong>` element exists yet, `**bold**` renders as
literal asterisk-wrapped text.

- [ ] **Step 4: Update the `answer_token` case in `EventLogLine.tsx`**

Add the import at the top of `frontend/src/components/EventLogLine.tsx`:

```tsx
import ReactMarkdown from 'react-markdown'
```

Replace the existing `'answer_token'` case:

```tsx
    case 'answer_token':
      return (
        <span>
          {event.text}
          {isTruncatedAnswer ? (
            <span className="text-amber-500"> [incomplete]</span>
          ) : null}
        </span>
      )
```

with:

```tsx
    case 'answer_token':
      return (
        <div>
          <ReactMarkdown>{event.text}</ReactMarkdown>
          {isTruncatedAnswer ? (
            <span className="text-amber-500"> [incomplete]</span>
          ) : null}
        </div>
      )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm test`
Expected: all tests pass, including the new markdown test and the
existing `'renders an answer_token'` / `'marks an answer_token as
truncated...'` tests (both should keep passing unchanged, per Step 2's
note — if either fails, read the actual rendered output before changing
the test, since a failure here likely means react-markdown's default
wrapping differs from what's assumed above, not that the test itself is
wrong).

- [ ] **Step 6: Manually verify in the browser**

With the backend running (`./.venv/bin/uvicorn coderag_mcp.api.main:app
--port 8000` from the repo root) and the frontend dev server running
(`npm run dev` in `frontend/`), submit one of the example questions and
confirm the final answer now shows real bold text, code blocks, and
markdown links instead of literal `**`/backtick/`[]()` syntax. Note the
result in your task report.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/EventLogLine.tsx frontend/src/components/EventLogLine.test.tsx
git commit -m "feat(frontend): render the final answer as real markdown"
```

---

### Task 4: Frontend — recolor reasoning, general log cleanup

**Files:**
- Modify: `frontend/src/components/EventLogLine.tsx`
- Modify: `frontend/src/components/EventLogLine.test.tsx`
- Modify: `frontend/src/components/RunCard.tsx`

**Interfaces:**
- Consumes: nothing new from earlier tasks.
- Produces: no interface changes — purely visual/CSS-class changes to
  existing components.

- [ ] **Step 1: Write the failing test for the reasoning color**

In `frontend/src/components/EventLogLine.test.tsx`, update the existing
`'renders reasoning text'` test:

```tsx
  it('renders reasoning text in violet', () => {
    const { container } = render(
      <EventLogLine event={{ type: 'reasoning', text: 'thinking about auth' }} />,
    )
    expect(screen.getByText(/thinking about auth/)).toBeInTheDocument()
    expect(container.querySelector('.text-violet-400')).not.toBeNull()
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — the current `reasoning` case uses `text-slate-500`, not
`text-violet-400`.

- [ ] **Step 3: Recolor `reasoning` and add overflow/spacing cleanup**

In `frontend/src/components/EventLogLine.tsx`, change the `reasoning`
case from:

```tsx
    case 'reasoning':
      return <div className="italic text-slate-500">{event.text}</div>
```

to:

```tsx
    case 'reasoning':
      return <div className="italic text-violet-400">{event.text}</div>
```

Then add overflow-safe wrapping to the two cases that render
potentially-long, single-line technical content — `tool_call` (its
`JSON.stringify(event.input)`) and `tool_result` (its `output_preview`).
Change:

```tsx
    case 'tool_call':
      return (
        <div className="text-sky-400">
          → {event.tool}({JSON.stringify(event.input)})
        </div>
      )
```

to:

```tsx
    case 'tool_call':
      return (
        <div className="overflow-x-auto whitespace-pre-wrap text-sky-400">
          → {event.tool}({JSON.stringify(event.input)})
        </div>
      )
```

and change:

```tsx
    case 'tool_result':
      return (
        <div className={event.is_error ? 'text-red-400' : 'text-emerald-400'}>
          {event.is_error ? '✗' : '✓'} {event.tool}: {event.output_preview}
          {event.is_error ? ' (error)' : ''}
        </div>
      )
```

to:

```tsx
    case 'tool_result':
      return (
        <div
          className={
            'overflow-x-auto whitespace-pre-wrap ' +
            (event.is_error ? 'text-red-400' : 'text-emerald-400')
          }
        >
          {event.is_error ? '✗' : '✓'} {event.tool}: {event.output_preview}
          {event.is_error ? ' (error)' : ''}
        </div>
      )
```

- [ ] **Step 3b: Align icons consistently across event types**

The design spec also calls for "consistent left-icon alignment across
event types... using a shared small layout tweak rather than per-case ad
hoc spacing." Today each icon (`→`, `✓`/`✗`, `⚠`) is inline text mixed
directly into each case's string content, so icon-to-text alignment drifts
slightly depending on surrounding text length. Fix by wrapping the icon in
its own non-shrinking flex item, consistently, in the three cases that
have a leading icon (`tool_call`, `tool_result`, and `no_semantic_index`
from Task 2).

Change `tool_call` from:

```tsx
    case 'tool_call':
      return (
        <div className="overflow-x-auto whitespace-pre-wrap text-sky-400">
          → {event.tool}({JSON.stringify(event.input)})
        </div>
      )
```

to:

```tsx
    case 'tool_call':
      return (
        <div className="flex items-start gap-2 overflow-x-auto whitespace-pre-wrap text-sky-400">
          <span className="shrink-0">→</span>
          <span>{event.tool}({JSON.stringify(event.input)})</span>
        </div>
      )
```

Change `tool_result` from:

```tsx
    case 'tool_result':
      return (
        <div
          className={
            'overflow-x-auto whitespace-pre-wrap ' +
            (event.is_error ? 'text-red-400' : 'text-emerald-400')
          }
        >
          {event.is_error ? '✗' : '✓'} {event.tool}: {event.output_preview}
          {event.is_error ? ' (error)' : ''}
        </div>
      )
```

to:

```tsx
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
```

Change `no_semantic_index` (added in Task 2) from:

```tsx
    case 'no_semantic_index':
      return <div className="text-amber-400">⚠ {event.message}</div>
```

to:

```tsx
    case 'no_semantic_index':
      return (
        <div className="flex items-start gap-2 text-amber-400">
          <span className="shrink-0">⚠</span>
          <span>{event.message}</span>
        </div>
      )
```

These are purely structural (splitting one text node into icon-span +
content-span) — no visible text changes, so no test assertions should
need updating for this step specifically. Run the tests after this step
regardless to confirm (`getByText` matches on an element's combined
normalized text content across child elements by default, so splitting
`→ {tool}(...)` into two sibling `<span>`s under the same parent `<div>`
still matches the same combined text via `getByText`).

- [ ] **Step 4: Increase log line spacing in `RunCard.tsx`**

In `frontend/src/components/RunCard.tsx`, change the log container's
class from `flex flex-col gap-1 font-mono text-sm` to `flex flex-col
gap-2 font-mono text-sm` (one step up on Tailwind's spacing scale, a
small readability improvement without restructuring the layout):

```tsx
      <div className="flex flex-col gap-2 font-mono text-sm">
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm test`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EventLogLine.tsx frontend/src/components/EventLogLine.test.tsx frontend/src/components/RunCard.tsx
git commit -m "feat(frontend): recolor reasoning to violet, add overflow wrapping and spacing to the event log"
```

---

### Task 5: Frontend — Spanish UI copy

**Files:**
- Modify: `frontend/src/components/RepoForm.tsx`
- Modify: `frontend/src/components/RepoForm.test.tsx`
- Modify: `frontend/src/components/RunCard.tsx`
- Modify: `frontend/src/components/RunCard.test.tsx`
- Modify: `frontend/src/components/EventLogLine.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: nothing new from earlier tasks.
- Produces: no interface changes — string replacement only.

- [ ] **Step 1: Update `RepoForm.tsx`'s copy**

In `frontend/src/components/RepoForm.tsx`, make these exact string
replacements:
- `<span>Repo URL</span>` → `<span>URL del repo</span>`
- `<span>Question</span>` → `<span>Pregunta</span>`
- `placeholder="https://github.com/owner/repo"` stays unchanged (not
  user-facing prose, it's already language-neutral)
- `placeholder="How does X work?"` → `placeholder="¿Cómo funciona X?"`
- `{showApiKey ? 'Hide' : 'Add'} API key (optional)` →
  `{showApiKey ? 'Ocultar' : 'Agregar'} API key (opcional)`
- `<span>API key</span>` stays unchanged ("API key" is a commonly
  unstranslated technical term in Spanish-language UIs, and the design
  spec explicitly keeps it as-is)
- `Try: {example.label}` → `Probar: {example.label}`
- `>Ask<` (the submit button's text content) → `>Preguntar<`

- [ ] **Step 2: Update `RepoForm.test.tsx`'s selectors to match**

In `frontend/src/components/RepoForm.test.tsx`, update every selector
that targeted the old English strings:
- `screen.getByLabelText(/repo url/i)` → `screen.getByLabelText(/url del repo/i)`
  (all 3 occurrences — lines with `await user.type(screen.getByLabelText(/repo url/i), ...)`
  twice and `const repoUrlInput = screen.getByLabelText(/repo url/i)` once)
- `screen.getByLabelText(/question/i)` → `screen.getByLabelText(/pregunta/i)`
  (all 3 occurrences)
- `screen.getByRole('button', { name: /ask/i })` →
  `screen.getByRole('button', { name: /preguntar/i })` (both occurrences)
- `screen.getByRole('button', { name: /add/i })` →
  `screen.getByRole('button', { name: /agregar/i })`
- `screen.getByLabelText(/api key/i)` stays unchanged (label text didn't
  change)
- `screen.getAllByRole('button', { name: /try:/i })` →
  `screen.getAllByRole('button', { name: /probar:/i })`

- [ ] **Step 3: Run `RepoForm`'s tests to verify they pass**

Run: `cd frontend && npm test -- RepoForm`
Expected: all `RepoForm` tests pass with the updated Spanish selectors.

- [ ] **Step 4: Update `RunCard.tsx`'s copy**

In `frontend/src/components/RunCard.tsx`, change:

```tsx
        {status === 'connecting' ? <div className="text-slate-500">Connecting...</div> : null}
```

to:

```tsx
        {status === 'connecting' ? <div className="text-slate-500">Conectando...</div> : null}
```

- [ ] **Step 5: Update `RunCard.test.tsx`**

`RunCard.test.tsx` doesn't currently assert on the "Connecting..." text
(check the file to confirm — its three tests assert on repo URL/question
header text, the merged answer text, and the truncated-answer marker,
none of which reference "Connecting..."), so no selector changes are
needed there for this step. Just confirm this by reading the file before
moving on.

- [ ] **Step 6: Update `EventLogLine.tsx`'s generated copy**

In `frontend/src/components/EventLogLine.tsx`, make these replacements:
- `Indexing {event.repo_url}...` → `Indexando {event.repo_url}...`
- `Indexed {event.chunk_count} chunks in {event.duration_s}s` →
  `Indexado {event.chunk_count} chunks en {event.duration_s}s`
- The `[incomplete]` marker text → `[incompleto]` (in the `answer_token`
  case's truncated-marker span)
- `Error: {event.message}` → `Error: {event.message}` stays unchanged
  ("Error" is spelled identically in Spanish)
- `(error)` suffix in the `tool_result` case stays unchanged (same word
  in both languages)
- The `no_semantic_index` case's rendering (`⚠ {event.message}`) stays
  unchanged as markup — `event.message` itself is already Spanish-free
  English text coming from the backend's Task 1 event, which is fine per
  the design spec's scope note (only this project's own static UI copy
  is being translated in this pass; the backend message string itself was
  written in English in Task 1 and is out of scope for translation here
  — flag this to the user as a follow-up if they want it localized too,
  don't silently translate backend strings as part of a frontend-only task)

- [ ] **Step 7: Update `EventLogLine.test.tsx`'s text assertions**

Find and update the two test assertions that check for the now-translated
strings:
- The test asserting `screen.getByText(/indexing/i)` (in the
  `'renders indexing_start'` test) → `screen.getByText(/indexando/i)`
- The test asserting on `[incomplete]` (in the `'marks an answer_token as
  truncated...'` test, `screen.getByText(/incomplete/i)`) →
  `screen.getByText(/incompleto/i)`

- [ ] **Step 8: Update `App.test.tsx`**

In `frontend/src/App.test.tsx`, change:

```tsx
    expect(screen.getByLabelText(/repo url/i)).toBeInTheDocument()
```

to:

```tsx
    expect(screen.getByLabelText(/url del repo/i)).toBeInTheDocument()
```

- [ ] **Step 9: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests pass (Tasks 1-5 combined).

- [ ] **Step 10: Manual smoke check**

With the backend and frontend dev servers running (as in Task 3's Step 6),
open the app in a browser and confirm every visible label/button/status
reads in Spanish: "URL del repo", "Pregunta", "Agregar API key
(opcional)", "Probar: ...", "Preguntar", "Conectando...", "Indexando...",
"Indexado N chunks en Xs". Note the result in your task report.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/RepoForm.tsx frontend/src/components/RepoForm.test.tsx frontend/src/components/RunCard.tsx frontend/src/components/EventLogLine.tsx frontend/src/components/EventLogLine.test.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): translate UI copy to Spanish"
```

---

## Final check

After Task 5, run `./.venv/bin/pytest -q` from the repo root and `npm
test` from `frontend/` once more and confirm both suites pass (97+
backend, 27+ frontend) before moving to
`superpowers:finishing-a-development-branch`.
