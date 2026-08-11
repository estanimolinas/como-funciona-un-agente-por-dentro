# UX polish fixes — design

## Context

A hands-on UX test of coderag-mcp's frontend (a subagent actually used the
live app end-to-end via a headless browser — 3 real runs, screenshots,
DOM inspection) surfaced 5 concrete, well-diagnosed issues. This spec
fixes all 5 in one batch — a bugfix/polish pass, not open design
exploration, following coderag-mcp's usual spec→plan→
subagent-driven-development workflow but moving through it quickly since
every fix is already fully specified.

## Fixes

**1. Markdown answers have no CSS for lists or code blocks (highest
priority).** `frontend/src/components/EventLogLine.tsx`'s `answer_token`
case renders `<ReactMarkdown>{event.text}</ReactMarkdown>` with zero
custom styling. The parsed HTML is correct (`<ul><li>`, `<pre><code>`
verified in the real DOM) but invisible as structure: no bullets/indent
on list items, no background/padding/border on code blocks. Fix: wrap the
markdown output in `<div className="markdown-answer">` and add scoped
CSS rules to `frontend/src/index.css` for `ul`/`ol`/`li`/`pre`/`code`/`a`
within that class. No new dependency (`@tailwindcss/typography` would add
a package and opinionated overrides for a handful of rules a few lines of
hand-written CSS covers just as well).

**2. Unrounded float in the indexing-duration line.**
`coderag_mcp/api/ask_stream_route.py:55` emits `"duration_s":
time.monotonic() - start` — a raw float (e.g. `1.273961832979694`),
displayed verbatim by `EventLogLine.tsx`'s `indexing_done` case. Fixed at
the source: `round(time.monotonic() - start, 2)`, so both the SSE JSON
and every future consumer get a clean value, not just the display layer.

**3. Tool-result previews leak the server's absolute clone-directory
path.** `coderag_mcp/orchestrator/ask.py`'s `_preview()` truncates
`ToolResultBlock.content` but does no path relativization — `Grep`/`Read`
output (running with `cwd=str(repo_dir)`) can include the full absolute
temp-clone path, repeated per matched line. Fix: `_preview()` gains a
`repo_dir: str` parameter; strips the `repo_dir + "/"` prefix from the
text before truncating. The one call site (`ask_stream()`, already has
`repo_dir` in scope) passes it through.

**4. Example-button questions aren't translated.** `RepoForm.tsx`'s
`EXAMPLES` array has Spanish button labels ("Probar: ...") but English
`question` text, which gets submitted to the backend. Fix: translate both
questions to Spanish — consistent with the rest of the now-fully-Spanish
UI, and the orchestrator answers in whatever language fits the question,
so this doesn't change backend behavior.

**5. No visual grouping in the event log beyond color.** Long runs read
as one dense undifferentiated column. Fix, kept deliberately simple: each
`tool_call` event (the natural start of a new "investigation step") gets
an extra `mt-2` on top of the log container's existing `gap-2`, visually
separating each step from the previous one's result — no new state, no
grouping data structure, a pure per-event-type CSS tweak in
`EventLogLine.tsx`'s `tool_call` case.

## Testing

- Frontend: a render test confirming the `answer_token` case wraps output
  in the `markdown-answer` class (structural, not pixel-value, since
  CSS-only visual correctness isn't practically unit-testable here — this
  project's established pattern for CSS-only changes, per the prior
  gitingest-redesign plan, is manual browser verification, not new test
  infrastructure). A test confirming the two `EXAMPLES` entries' `question`
  fields are in Spanish (a simple string-content assertion, not a new
  behavior).
- Backend: a test for `_preview()` confirming a `repo_dir`-prefixed path
  in the input content is stripped in the output; a test confirming
  `ask_stream()`'s `indexing_done`-equivalent duration value is rounded
  to 2 decimal places (existing tests in `tests/orchestrator/test_ask.py`
  and `tests/api/test_ask_stream_route.py` may already cover adjacent
  paths — extend rather than duplicate if so).
- Full existing suite (99 backend / 35 frontend at time of writing) must
  stay green.
- Manual verification: real browser check (per this project's established
  practice for visual changes) confirming markdown lists/code blocks
  render with real structure, the indexing-duration line shows a
  2-decimal value, a `Grep`-heavy answer's tool-result lines show relative
  not absolute paths, the example buttons submit Spanish questions, and
  the log shows a visible (if subtle) gap before each new tool call.
