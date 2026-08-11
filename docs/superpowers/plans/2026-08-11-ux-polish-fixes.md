# UX Polish Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 concrete issues found during real hands-on UX testing —
round the indexing-duration float, strip absolute clone-dir paths from
tool-result previews, style markdown lists/code blocks, translate the
example questions, and add visual spacing before each new tool call — per
`docs/superpowers/specs/2026-08-11-ux-polish-fixes-design.md`.

**Architecture:** Two backend fixes (rounding in `ask_stream_route.py`,
path-stripping in `ask.py`'s `_preview()`) land together since both are
small, same-module changes with overlapping test files. Two frontend
fixes (markdown CSS, example translation + log spacing) land as separate
tasks since they touch different concerns (global CSS vs. component
copy/layout) even though both are in `frontend/`.

**Tech Stack:** Python (existing backend), React+TS+Tailwind (existing
frontend). No new dependencies.

## Global Constraints

- `_preview()`'s new `repo_dir` parameter: confirmed via reading the
  current code that `ask_stream()` (the sole call site, at
  `coderag_mcp/orchestrator/ask.py:178`) has `repo_dir` in scope as a
  `pathlib.Path`, assigned at line 86 via `await
  asyncio.to_thread(clone.clone_repo, ...)`. Pass `str(repo_dir)` at the
  call site.
- `duration_s` rounding happens at the source (`ask_stream_route.py`),
  not the display layer — `round(time.monotonic() - start, 2)`.
- Markdown CSS is hand-written rules scoped to a `.markdown-answer` class
  wrapper — no new npm dependency (`@tailwindcss/typography` was
  considered and rejected as disproportionate for a handful of rules).
- Example question translations (exact text, verbatim):
  - `'How is the package version defined?'` → `'¿Cómo se define la versión del paquete?'`
  - `'How does the @click.command decorator work?'` → `'¿Cómo funciona el decorador @click.command?'`
- Tool-call spacing: `mt-2` added to the `tool_call` case's wrapper div,
  on top of the existing `gap-2` on `RunCard`'s log container — no new
  state, no grouping data structure.
- Full test suite must stay green: **99 backend / 35 frontend** at
  plan-writing time.

---

### Task 1: Backend — round indexing duration, strip clone-dir paths from previews

**Files:**
- Modify: `coderag_mcp/api/ask_stream_route.py`
- Modify: `coderag_mcp/orchestrator/ask.py`
- Test: `tests/api/test_ask_stream_route.py`
- Test: `tests/orchestrator/test_ask.py`

**Interfaces:**
- Produces: `_preview(content: str | list[dict] | None, repo_dir: str) ->
  str` in `coderag_mcp/orchestrator/ask.py` — signature change (new
  required second parameter), only caller is `ask_stream()` in the same
  file, updated in this task.

- [ ] **Step 1: Write the failing test for duration rounding**

Add to `tests/api/test_ask_stream_route.py`, extending the existing
`test_ask_stream_indexes_then_streams_orchestrator_events` test (find it
— it already asserts `types == [...]` and `events[0]["repo_url"] ==
...`). Add this assertion right after the existing ones, inside the same
test function:

```python
    duration = events[1]["duration_s"]
    assert isinstance(duration, float)
    assert round(duration, 2) == duration
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/api/test_ask_stream_route.py::test_ask_stream_indexes_then_streams_orchestrator_events -v`
Expected: FAIL — `duration_s` currently has full float precision, so
`round(duration, 2) == duration` is false for a real elapsed-time value
almost all the time (e.g. `1.273961832979694 != 1.27`).

- [ ] **Step 3: Round `duration_s` in `ask_stream_route.py`**

In `coderag_mcp/api/ask_stream_route.py`, find the line:

```python
                "duration_s": time.monotonic() - start,
```

Change it to:

```python
                "duration_s": round(time.monotonic() - start, 2),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/api/test_ask_stream_route.py -v`
Expected: all tests pass.

- [ ] **Step 5: Write the failing test for path-stripping in `_preview()`**

Add to `tests/orchestrator/test_ask.py`, a new test (place it near the
existing `test_ask_stream_truncates_long_tool_results` test, following the
same pattern — `conn = MagicMock()`, patch `clone.clone_repo` to return
`tmp_path`, patch `count_chunks`, patch `query` with a scripted stream):

```python
@pytest.mark.asyncio
async def test_ask_stream_strips_clone_dir_prefix_from_tool_result_preview(tmp_path):
    conn = MagicMock()
    absolute_match_line = f"{tmp_path}/README.md:3:some matched text"

    async def _one_tool_result(*, prompt, options):
        yield AssistantMessage(
            content=[ToolUseBlock(id="toolu_1", name="Grep", input={"pattern": "text"})],
            model="test",
        )
        yield UserMessage(content=[ToolResultBlock(tool_use_id="toolu_1", content=absolute_match_line)])

    with (
        patch("coderag_mcp.orchestrator.ask.build_search_server", return_value=object()),
        patch("coderag_mcp.orchestrator.ask.clone.clone_repo", return_value=tmp_path),
        patch("coderag_mcp.orchestrator.ask.clone.cleanup_clone"),
        patch("coderag_mcp.orchestrator.ask.count_chunks", return_value=5),
        patch("coderag_mcp.orchestrator.ask.query", side_effect=_one_tool_result),
    ):
        events = [
            event
            async for event in ask_stream(conn, repo_id=1, repo_url="https://github.com/a/b", question="?")
        ]

    tool_result_event = next(e for e in events if e["type"] == "tool_result")
    assert tool_result_event["output_preview"] == "README.md:3:some matched text"
    assert str(tmp_path) not in tool_result_event["output_preview"]
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py::test_ask_stream_strips_clone_dir_prefix_from_tool_result_preview -v`
Expected: FAIL — `_preview()` doesn't strip any prefix yet, so
`output_preview` still contains the full `tmp_path`-prefixed string.

- [ ] **Step 7: Update `_preview()` to strip the clone-dir prefix**

In `coderag_mcp/orchestrator/ask.py`, change the function signature and
body from:

```python
def _preview(content: str | list[dict] | None) -> str:
    """Render a ToolResultBlock's content as a short, truncated preview string.

    content is str for most tools (Read, Glob, Grep, search_code all return plain
    text), but the SDK's type allows a list of content-block dicts too - handle both
    rather than assuming, since ToolResultBlock.content's type hint permits either.
    """
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    else:
        text = "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    if len(text) > _PREVIEW_LIMIT:
        return text[:_PREVIEW_LIMIT] + "... (truncated)"
    return text
```

to:

```python
def _preview(content: str | list[dict] | None, repo_dir: str) -> str:
    """Render a ToolResultBlock's content as a short, truncated preview string.

    content is str for most tools (Read, Glob, Grep, search_code all return plain
    text), but the SDK's type allows a list of content-block dicts too - handle both
    rather than assuming, since ToolResultBlock.content's type hint permits either.

    repo_dir is the absolute path Read/Grep/Glob operate under (ClaudeAgentOptions'
    cwd) - their raw output can include it verbatim, leaking the server's temp
    directory layout to the client; strip it so previews show paths relative to the
    repo root instead.
    """
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    else:
        text = "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    text = text.replace(repo_dir + "/", "")
    if len(text) > _PREVIEW_LIMIT:
        return text[:_PREVIEW_LIMIT] + "... (truncated)"
    return text
```

Then update the one call site, changing:

```python
                                    "output_preview": _preview(block.content),
```

to:

```python
                                    "output_preview": _preview(block.content, str(repo_dir)),
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/orchestrator/test_ask.py -v`
Expected: all tests pass, including the new one — confirm the two other
tests calling `_preview()` indirectly (`test_ask_stream_yields_one_event_per_block`,
`test_ask_stream_truncates_long_tool_results`) still pass unchanged, since
their tool-result content strings never contained the clone-dir prefix to
begin with, so `.replace()` is a no-op for them.

- [ ] **Step 9: Run the full backend suite**

Run: `./.venv/bin/pytest -q`
Expected: all tests pass, no regressions elsewhere.

- [ ] **Step 10: Commit**

```bash
git add coderag_mcp/api/ask_stream_route.py coderag_mcp/orchestrator/ask.py tests/api/test_ask_stream_route.py tests/orchestrator/test_ask.py
git commit -m "fix(backend): round indexing duration, strip clone-dir paths from tool-result previews"
```

---

### Task 2: Frontend — markdown CSS for lists and code blocks

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/components/EventLogLine.tsx`
- Modify: `frontend/src/components/EventLogLine.test.tsx`

**Interfaces:**
- Consumes: nothing from Task 1 (frontend-only, independent of the
  backend fixes).
- Produces: no interface changes — `answer_token`'s rendered markup gains
  a `markdown-answer` wrapper class, no prop/type changes.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/EventLogLine.test.tsx` (near the existing
markdown test, `'renders markdown syntax in an answer_token as real
formatting, not raw text'`):

```tsx
  it('wraps the rendered markdown in the markdown-answer styling class', () => {
    const { container } = render(
      <EventLogLine event={{ type: 'answer_token', text: 'plain text' }} />,
    )
    expect(container.querySelector('.markdown-answer')).not.toBeNull()
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- EventLogLine` (in `frontend/`)
Expected: FAIL — no element has the `markdown-answer` class yet.

- [ ] **Step 3: Add the wrapper class**

In `frontend/src/components/EventLogLine.tsx`, change the `answer_token`
case from:

```tsx
    case 'answer_token':
      return (
        <div>
          <ReactMarkdown>{event.text}</ReactMarkdown>
          {isTruncatedAnswer ? (
            <span className="text-amber-500"> [incompleto]</span>
          ) : null}
        </div>
      )
```

to:

```tsx
    case 'answer_token':
      return (
        <div>
          <div className="markdown-answer">
            <ReactMarkdown>{event.text}</ReactMarkdown>
          </div>
          {isTruncatedAnswer ? (
            <span className="text-amber-500"> [incompleto]</span>
          ) : null}
        </div>
      )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- EventLogLine` (in `frontend/`)
Expected: passes.

- [ ] **Step 5: Add the CSS rules**

In `frontend/src/index.css`, append (after the existing `body { ... }`
block):

```css
.markdown-answer ul,
.markdown-answer ol {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.markdown-answer ul {
  list-style-type: disc;
}

.markdown-answer ol {
  list-style-type: decimal;
}

.markdown-answer li {
  margin: 0.25rem 0;
}

.markdown-answer p {
  margin: 0.5rem 0;
}

.markdown-answer pre {
  background-color: var(--color-slate-900, #0f172a);
  border: 1px solid var(--color-slate-700, #334155);
  border-radius: 0.375rem;
  padding: 0.75rem;
  overflow-x: auto;
  margin: 0.5rem 0;
}

.markdown-answer code {
  background-color: var(--color-slate-900, #0f172a);
  border-radius: 0.25rem;
  padding: 0.125rem 0.25rem;
}

.markdown-answer pre code {
  background-color: transparent;
  padding: 0;
}

.markdown-answer a {
  color: var(--color-sky-400, #38bdf8);
  text-decoration: underline;
}
```

- [ ] **Step 6: Manually verify in the browser**

With the backend running (`./.venv/bin/uvicorn coderag_mcp.api.main:app
--port 8000` from the repo root) and the frontend dev server running
(`npm run dev` in `frontend/`), submit one of the example questions and
confirm the final answer's bullet lists show real bullets/indentation and
any code blocks show a visible dark background with padding and rounded
corners, not blending into the surrounding text. Note the result in your
task report.

- [ ] **Step 7: Run the full frontend test suite**

Run: `npm test` (in `frontend/`)
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/index.css frontend/src/components/EventLogLine.tsx frontend/src/components/EventLogLine.test.tsx
git commit -m "fix(frontend): style markdown lists and code blocks in the final answer"
```

---

### Task 3: Frontend — translate example questions, add tool-call spacing

**Files:**
- Modify: `frontend/src/components/RepoForm.tsx`
- Modify: `frontend/src/components/RepoForm.test.tsx`
- Modify: `frontend/src/components/EventLogLine.tsx`

**Interfaces:**
- Consumes: nothing from Tasks 1-2 (independent).
- Produces: no interface changes — copy and spacing only.

- [ ] **Step 1: Write the failing test for translated example questions**

Add to `frontend/src/components/RepoForm.test.tsx` (near the existing
`'fills the form when an example button is clicked'` test):

```tsx
  it('fills the form with Spanish example questions', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.click(screen.getAllByRole('button', { name: /probar:/i })[0])

    const questionInput = screen.getByLabelText(/pregunta/i) as HTMLInputElement
    expect(questionInput.value).toMatch(/^¿/)
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- RepoForm` (in `frontend/`)
Expected: FAIL — the first example's question is still
`'How is the package version defined?'`, which doesn't start with `¿`.

- [ ] **Step 3: Translate the example questions**

In `frontend/src/components/RepoForm.tsx`, find the `EXAMPLES` array:

```tsx
const EXAMPLES: { label: string; repoUrl: string; question: string }[] = [
  {
    label: 'pypa/sampleproject — How is the package version defined?',
    repoUrl: 'https://github.com/pypa/sampleproject',
    question: 'How is the package version defined?',
  },
  {
    label: 'pallets/click — How does the @click.command decorator work?',
    repoUrl: 'https://github.com/pallets/click',
    question: 'How does the @click.command decorator work?',
  },
]
```

Change the `question` fields (leave `label` and `repoUrl` unchanged):

```tsx
const EXAMPLES: { label: string; repoUrl: string; question: string }[] = [
  {
    label: 'pypa/sampleproject — How is the package version defined?',
    repoUrl: 'https://github.com/pypa/sampleproject',
    question: '¿Cómo se define la versión del paquete?',
  },
  {
    label: 'pallets/click — How does the @click.command decorator work?',
    repoUrl: 'https://github.com/pallets/click',
    question: '¿Cómo funciona el decorador @click.command?',
  },
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- RepoForm` (in `frontend/`)
Expected: passes.

- [ ] **Step 5: Add spacing before each new tool call**

In `frontend/src/components/EventLogLine.tsx`, find the `tool_call` case:

```tsx
    case 'tool_call':
      return (
        <div className="flex items-start gap-2 overflow-x-auto whitespace-pre-wrap text-sky-400">
          <span className="shrink-0">→</span>
          <span>{event.tool}({JSON.stringify(event.input)})</span>
        </div>
      )
```

Add `mt-2` to the wrapper div's class list:

```tsx
    case 'tool_call':
      return (
        <div className="mt-2 flex items-start gap-2 overflow-x-auto whitespace-pre-wrap text-sky-400">
          <span className="shrink-0">→</span>
          <span>{event.tool}({JSON.stringify(event.input)})</span>
        </div>
      )
```

- [ ] **Step 6: Run the full frontend test suite**

Run: `npm test` (in `frontend/`)
Expected: all tests pass — confirm no existing `tool_call` render test
broke (none should, since this only adds a class, doesn't change any
text content or element structure).

- [ ] **Step 7: Manually verify in the browser**

With both dev servers running (as in Task 2's Step 6), submit a question
against a repo with multiple tool calls (e.g. a non-Python repo like
`https://github.com/jonschlinkert/is-odd` to trigger several `Read`/`Grep`
calls via the `no_semantic_index` fallback path) and confirm: the
questions/examples read in Spanish, and each new tool-call line has a
visibly larger gap above it than the lines within one tool-call/
tool-result pair. Note the result in your task report.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/RepoForm.tsx frontend/src/components/RepoForm.test.tsx frontend/src/components/EventLogLine.tsx
git commit -m "fix(frontend): translate example questions, add spacing before each tool call"
```

---

## Final check

After Task 3, run `./.venv/bin/pytest -q` once more from the repo root
and `npm test` once more from `frontend/`, and confirm both suites pass
(99 backend, 35 pre-existing + 3 new frontend tests = 38) before moving to
`superpowers:finishing-a-development-branch`.
