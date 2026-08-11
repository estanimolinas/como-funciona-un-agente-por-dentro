# Gitingest Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt gitingest.com's visual language (offset-shadow "sticker"
panels, thick borders, coral/amber brand accents, bold title+subtitle)
into coderag-mcp's existing dark theme, plus add two always-visible
inline help texts, per
`docs/superpowers/specs/2026-08-11-gitingest-visual-redesign-design.md`.

**Architecture:** A new shared `OffsetCard` component implements the
offset-shadow effect once; `RepoForm` and `RunCard` each wrap their main
panel in it. `App.tsx` gets a bigger title/subtitle (no `OffsetCard`
involvement — confirmed against the committed spec, which only wraps
`RepoForm`'s form and each `RunCard`, not `App.tsx`'s header). The event
log's existing color palette (`EventLogLine.tsx`) is untouched — this
plan does not modify that file at all.

**Tech Stack:** React + TypeScript + Tailwind CSS v4 (existing project
stack, no new dependencies). Color tokens used below (`amber-500`,
`amber-950`, `amber-900`, `amber-700`, `rose-500`, `slate-100`,
`slate-950`) were confirmed present in the installed Tailwind v4's
default theme (`frontend/node_modules/tailwindcss/theme.css`) at
plan-writing time — no custom Tailwind config changes needed.

## Global Constraints

- Dark mode is kept — this is an adaptation of gitingest's visual
  *language*, not a switch to gitingest's literal light/cream palette.
- The offset-shadow effect (a solid-color duplicate rectangle positioned
  behind a bordered panel via `translate-x-1 translate-y-1`) ships via a
  new shared `frontend/src/components/OffsetCard.tsx` component — no
  per-call-site duplication of the two-div pattern.
- Brand accent colors (`rose-500` for the logo accent, `amber-500` for
  the primary CTA, `amber-950`/`amber-900`/`amber-700` for example
  buttons) are scoped to chrome/branding only. **`EventLogLine.tsx` is
  not modified by this plan at all** — its existing sky/emerald/red/
  violet/amber event-type palette stays exactly as-is.
- Inline help text is always-visible (no tooltips), styled
  `text-xs text-slate-500` (or `text-slate-500` at the surrounding
  font size for `RunCard`'s preamble, since it sits among
  `text-sm`-sized siblings — see Task 4).
- Exact copy strings (verbatim, do not paraphrase):
  - API key helper: `Opcional — solo necesario si tu servidor tiene CODERAG_API_KEY configurada.`
  - Event log preamble: `Así explora y responde el agente, en vivo:`
- `OffsetCard`'s interface: `OffsetCard(props: { children: ReactNode;
  className?: string }) -> JSX.Element`. `className` is applied to the
  visible (front) panel, not the shadow layer. No other props — no
  per-call-site shadow-color override, since every consumer in this plan
  uses the same `bg-black` shadow (YAGNI: a configurable shadow color has
  no current caller that needs it).
- Full test suite must stay green: **99 backend / 29 frontend** at
  plan-writing time. This plan is frontend-only — the backend suite
  should be completely unaffected; run it once at the end to confirm.

---

### Task 1: `OffsetCard` — the shared offset-shadow component

**Files:**
- Create: `frontend/src/components/OffsetCard.tsx`
- Test: `frontend/src/components/OffsetCard.test.tsx`

**Interfaces:**
- Produces (used by Tasks 3-4): `OffsetCard(props: { children: ReactNode;
  className?: string }) -> JSX.Element`, exported from
  `frontend/src/components/OffsetCard.tsx`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/OffsetCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { OffsetCard } from './OffsetCard'

describe('OffsetCard', () => {
  it('renders its children', () => {
    render(<OffsetCard>contenido</OffsetCard>)
    expect(screen.getByText('contenido')).toBeInTheDocument()
  })

  it('renders a shadow layer behind the visible panel', () => {
    const { container } = render(<OffsetCard>x</OffsetCard>)
    const wrapper = container.firstElementChild
    expect(wrapper).not.toBeNull()
    const layers = wrapper!.children
    expect(layers).toHaveLength(2)
    expect(layers[0].className).toMatch(/translate-x-1/)
    expect(layers[0].className).toMatch(/translate-y-1/)
    expect(layers[1].className).toMatch(/border-2/)
  })

  it('applies an optional className to the visible panel, not the shadow layer', () => {
    const { container } = render(<OffsetCard className="p-4">x</OffsetCard>)
    const wrapper = container.firstElementChild!
    const [shadowLayer, panel] = wrapper.children
    expect(panel.className).toMatch(/p-4/)
    expect(shadowLayer.className).not.toMatch(/p-4/)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (in `frontend/`)
Expected: FAIL — `OffsetCard` module doesn't exist yet.

- [ ] **Step 3: Implement `OffsetCard`**

Create `frontend/src/components/OffsetCard.tsx`:

```tsx
import type { ReactNode } from 'react'

interface OffsetCardProps {
  children: ReactNode
  className?: string
}

export function OffsetCard({ children, className = '' }: OffsetCardProps) {
  return (
    <div className="relative">
      <div className="absolute inset-0 translate-x-1 translate-y-1 rounded bg-black" />
      <div className={`relative z-10 rounded border-2 border-slate-100 ${className}`}>
        {children}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (in `frontend/`)
Expected: all `OffsetCard` tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/OffsetCard.tsx frontend/src/components/OffsetCard.test.tsx
git commit -m "feat(frontend): add OffsetCard, the shared offset-shadow panel component"
```

---

### Task 2: `App.tsx` — big title + subtitle

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: nothing from Task 1 (`App.tsx` does not use `OffsetCard` —
  confirmed against the committed spec, which only wraps `RepoForm`'s
  form and each `RunCard`, not the page header).
- Produces: no interface changes — this task only changes `App.tsx`'s
  rendered header markup.

- [ ] **Step 1: Write the failing test**

Replace `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('renders the page heading, subtitle, and the repo form', () => {
    render(<App />)
    // The wordmark is split across sibling elements (plain text + a
    // colored <span>), so getByText's default exact-string match won't
    // find it as one node — use a function matcher checking the parsed
    // element's combined text content instead.
    expect(
      screen.getByText((_, element) => element?.tagName.toLowerCase() === 'h1' && element.textContent === 'coderag-mcp'),
    ).toBeInTheDocument()
    expect(screen.getByText(/mirá en vivo cómo el agente explora el código/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/url del repo/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test` (in `frontend/`)
Expected: FAIL — the subtitle text doesn't exist yet (the heading
assertion may or may not already pass depending on current markup; either
way, the subtitle assertion fails).

- [ ] **Step 3: Update `App.tsx`'s header**

In `frontend/src/App.tsx`, replace:

```tsx
      <h1 className="text-3xl font-bold">coderag-mcp</h1>
```

with:

```tsx
      <div className="flex flex-col gap-2">
        <h1 className="text-4xl font-bold tracking-tight">
          code<span className="text-rose-500">rag</span>-mcp
        </h1>
        <p className="text-slate-400">
          Mirá en vivo cómo el agente explora el código para responder.
        </p>
      </div>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test` (in `frontend/`)
Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): add a large title and subtitle above the form"
```

---

### Task 3: `RepoForm` — offset-shadow panel, brand colors, API-key help text

**Files:**
- Modify: `frontend/src/components/RepoForm.tsx`
- Modify: `frontend/src/components/RepoForm.test.tsx`

**Interfaces:**
- Consumes: `OffsetCard` from Task 1 (`import { OffsetCard } from
  './OffsetCard'`).
- Produces: no interface changes — `RepoForm`'s props/`onSubmit` contract
  is unchanged, only its rendered markup and styling change.

- [ ] **Step 1: Write the failing test for the API-key help text**

Add to `frontend/src/components/RepoForm.test.tsx` (this file already has
`beforeEach(() => localStorage.clear())` and other tests — add this as a
new `it` block inside the existing `describe('RepoForm', ...)`):

```tsx
  it('shows an always-visible explanation when the API key field is expanded', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    expect(screen.queryByText(/CODERAG_API_KEY/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /agregar/i }))

    expect(screen.getByText(/opcional.*CODERAG_API_KEY.*configurada/i)).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- RepoForm` (in `frontend/`)
Expected: FAIL — no element matches `/opcional.*CODERAG_API_KEY.*configurada/i` yet.

- [ ] **Step 3: Wrap the form in `OffsetCard` and update its styling**

In `frontend/src/components/RepoForm.tsx`, add the import:

```tsx
import { OffsetCard } from './OffsetCard'
```

Replace the `<form onSubmit={handleSubmit} className="flex flex-col gap-3">`
opening tag and its matching closing `</form>` — the whole form's content
stays the same, only the outer wrapper changes. Change:

```tsx
  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
```

to:

```tsx
  return (
    <OffsetCard className="p-6">
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
```

and change the closing:

```tsx
    </form>
  )
}
```

to:

```tsx
    </form>
    </OffsetCard>
  )
}
```

(Indentation inside the form body does not need to change — this is
purely wrapping the existing `<form>` element in `<OffsetCard>`.)

- [ ] **Step 4: Update input/button borders and brand colors**

Still in `frontend/src/components/RepoForm.tsx`, make these class changes:

Repo URL input — change `className="rounded border border-slate-700 bg-slate-900 px-3 py-2"` to:
```tsx
          className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
```

Question input — same change (both text inputs get the same treatment):
```tsx
          className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
```

API key input — same change:
```tsx
            className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
```

Example buttons — change `className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-400"` to:
```tsx
            className="rounded border-2 border-amber-700 bg-amber-950 px-2 py-1 text-xs text-amber-100 hover:bg-amber-900"
```

Submit button — change `className="self-start rounded bg-sky-600 px-4 py-2 font-semibold text-white"` to:
```tsx
        className="self-start rounded border-2 border-slate-100 bg-amber-500 px-4 py-2 font-semibold text-slate-950 hover:bg-amber-400"
```

- [ ] **Step 5: Add the API-key helper text**

Still in `frontend/src/components/RepoForm.tsx`, inside the
`{showApiKey ? (...) : null}` block, add a help paragraph right after the
API key `<label>`'s closing tag but still inside the same conditional
block. Change:

```tsx
      {showApiKey ? (
        <label className="flex flex-col gap-1">
          <span>API key</span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
          />
        </label>
      ) : null}
```

to:

```tsx
      {showApiKey ? (
        <>
          <label className="flex flex-col gap-1">
            <span>API key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
            />
          </label>
          <p className="text-xs text-slate-500">
            Opcional — solo necesario si tu servidor tiene CODERAG_API_KEY configurada.
          </p>
        </>
      ) : null}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm test` (in `frontend/`)
Expected: all `RepoForm` tests pass, including the new one — confirm the
pre-existing tests (submit behavior, example-fill behavior, empty-field
guard) still pass unchanged, since none of Steps 3-5 touched form
behavior, only markup/styling/the one new help paragraph.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/RepoForm.tsx frontend/src/components/RepoForm.test.tsx
git commit -m "feat(frontend): apply offset-shadow panel and brand colors to RepoForm, add API-key help text"
```

---

### Task 4: `RunCard` — offset-shadow panel, event-log preamble

**Files:**
- Modify: `frontend/src/components/RunCard.tsx`
- Modify: `frontend/src/components/RunCard.test.tsx`

**Interfaces:**
- Consumes: `OffsetCard` from Task 1 (`import { OffsetCard } from
  './OffsetCard'`).
- Produces: no interface changes — `RunCard`'s props contract is
  unchanged, only its rendered markup/styling and one new preamble line
  are added. `EventLogLine.tsx` is not touched by this task (the preamble
  line lives in `RunCard`'s own JSX, above where it maps `renderItems` to
  `<EventLogLine>` — confirmed against the current file: that mapping is
  a plain `.map()` call inside `RunCard`'s returned JSX, not inside
  `EventLogLine` itself).

- [ ] **Step 1: Write the failing test for the event-log preamble**

Add to `frontend/src/components/RunCard.test.tsx` (inside the existing
`describe('RunCard', ...)` block, using the file's existing
`fakeResponse` helper):

```tsx
  it('shows a preamble line above the event log', async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse(['data: {"type": "done"}\n\n']))
    render(<RunCard repoUrl="https://github.com/a/b" question="q" />)

    expect(await screen.findByText(/así explora y responde el agente/i)).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- RunCard` (in `frontend/`)
Expected: FAIL — no element matches `/así explora y responde el agente/i` yet.

- [ ] **Step 3: Wrap the card in `OffsetCard` and add the preamble line**

In `frontend/src/components/RunCard.tsx`, add the import:

```tsx
import { OffsetCard } from './OffsetCard'
```

Replace the returned JSX. Change:

```tsx
  return (
    <div className="rounded border border-slate-800 p-4">
      <div className="mb-2 text-sm text-slate-400">
        {repoUrl} — {question}
      </div>
      <div className="flex flex-col gap-2 font-mono text-sm">
        {status === 'connecting' ? <div className="text-slate-500">Conectando...</div> : null}
        {renderItems.map(({ key, event }) => (
          <EventLogLine
            key={key}
            event={event}
            isTruncatedAnswer={isTruncated && event.type === 'answer_token'}
          />
        ))}
      </div>
    </div>
  )
}
```

to:

```tsx
  return (
    <OffsetCard className="p-4">
      <div className="mb-2 text-sm text-slate-400">
        {repoUrl} — {question}
      </div>
      <p className="mb-2 text-xs text-slate-500">Así explora y responde el agente, en vivo:</p>
      <div className="flex flex-col gap-2 font-mono text-sm">
        {status === 'connecting' ? <div className="text-slate-500">Conectando...</div> : null}
        {renderItems.map(({ key, event }) => (
          <EventLogLine
            key={key}
            event={event}
            isTruncatedAnswer={isTruncated && event.type === 'answer_token'}
          />
        ))}
      </div>
    </OffsetCard>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (in `frontend/`)
Expected: all `RunCard` tests pass, including the new one — confirm the
pre-existing tests (header text, merged answer text, truncated-answer
marker) still pass unchanged, since `OffsetCard` only adds wrapping
elements and the preamble line doesn't remove or alter any existing text.

- [ ] **Step 5: Manually verify in the browser**

With the backend running (`./.venv/bin/uvicorn coderag_mcp.api.main:app
--port 8000` from the repo root) and the frontend dev server running
(`npm run dev` in `frontend/`), submit one of the example questions and
confirm: the form and each answer card show the offset-shadow "sticker"
effect, the submit button and example buttons show the new amber/coral
brand colors, the title shows "code**rag**-mcp" with "rag" in coral, the
subtitle appears under the title, the API-key helper text appears when
that field is expanded, and the "Así explora y responde el agente, en
vivo:" line appears above each card's event log. Note the result in your
task report.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RunCard.tsx frontend/src/components/RunCard.test.tsx
git commit -m "feat(frontend): apply offset-shadow panel to RunCard, add event-log preamble text"
```

---

## Final check

After Task 4, run `npm test` once more from `frontend/` and
`./.venv/bin/pytest -q` once more from the repo root, and confirm both
suites pass — 99 backend (unaffected by this plan) plus 29 pre-existing
frontend tests plus 5 new ones added across this plan (3 in Task 1's
`OffsetCard.test.tsx`, 1 in Task 3's `RepoForm.test.tsx`, 1 in Task 4's
`RunCard.test.tsx`; Task 2's `App.test.tsx` change extends an existing
test rather than adding a new one) — before moving to
`superpowers:finishing-a-development-branch`.
