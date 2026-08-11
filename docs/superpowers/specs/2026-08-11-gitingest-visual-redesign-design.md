# Gitingest-style visual redesign + inline help copy — design

## Context

coderag-mcp's frontend (React+Vite+TS+Tailwind) is fully built and
functional: a form (repo URL, question, optional API key, example
buttons), a live event log ("x-ray" into the orchestrator's tool calls,
reasoning, and streamed answer via SSE), markdown-rendered answers,
Spanish UI copy, dark theme. This shipped across two prior plans (the
original build, then a polish pass fixing markdown rendering, event
colors, and translation).

The original frontend design spec
(`docs/superpowers/specs/2026-08-10-frontend-design.md`) explicitly scoped
gitingest.com as inspiration for "ethos, not literal look" — a deliberate
choice to avoid copying gitingest's exact visual language, keeping only
its "paste and go, one screen, minimal chrome" simplicity. After actually
using the shipped product, the user revisited that decision: the current
UI doesn't read as gitingest-inspired at all, and they want it to now.
**This spec explicitly reopens that earlier decision** — it's not a bug
fix, it's a scope change made with full context of what shipped.

Separately, the user hit a concrete UX gap while testing: the optional
API key field has no explanation of what it's for or when it's needed,
so it reads as confusing noise for the common case (local use, no auth
configured). This surfaced a broader ask: unclear UI elements in general
should explain themselves inline, not just this one field.

Both changes touch the same components (`RepoForm`, `RunCard`, `App.tsx`),
so this is one cohesive plan, not two.

## Reference material

The user provided gitingest.com's actual current HTML/CSS source
directly (not a description or a mockup) — the design below is built
from real, verified design tokens, not visual guesswork:

- **Palette:** cream background (`#FFFDF8`), near-black text/borders
  (`gray-900`), coral accent (`#FE4A60`, used for the "ingest" half of
  the logo and a gradient), amber accent (`#ffc480`, the primary "Ingest"
  button and tooltip backgrounds), light-blue input backgrounds
  (`#E8F0FE`), tan example-button background (`#EBDBB7`, hover `#FFC480`).
- **Signature visual motif — the "offset shadow":** every key element
  (main panel, inputs, buttons, the results section) has a solid-color
  duplicate rectangle positioned behind it via `translate-x`/`translate-y`
  (typically 4-8px), creating a hard-edged layered/sticker look with no
  blur — e.g. `<div class="... bg-gray-900 rounded-xl translate-y-2
  translate-x-2 absolute inset-0"></div>` sitting behind the main
  container.
- **Borders:** thick (3px), solid, near-black, on every interactive
  element and panel.
- **Typography:** bold sans-serif for headings (`font-bold
  tracking-tighter`, large — up to `text-7xl` for the page title), plain
  sans-serif body text, monospace for technical/code content (the
  directory-structure and file-content result panels).
- **Layout:** single centered column (`max-w-4xl`), large title +
  subtitle, then an input+button row, a secondary controls row, example
  repo buttons, then a results panel below — all following the same
  offset-shadow-and-thick-border treatment.
- **Critically: gitingest is light mode**, not dark. This is a real,
  confirmed divergence point from coderag-mcp's existing dark theme,
  addressed explicitly below (not glossed over).

## Decisions (confirmed with the user)

1. **Dark mode is kept, not replaced.** coderag-mcp adapts gitingest's
   visual *language* (offset shadows, thick borders, bold typography,
   coral/amber accents) into a dark palette, rather than switching to
   gitingest's literal cream/light-mode look. Rationale: a technical demo
   run for extended periods, and contrast against the event log's
   terminal-style color coding, both favor dark — matching gitingest
   pixel-for-pixel would mean abandoning a choice that's still right for
   this product's actual use case.
2. **The offset-shadow effect ships** — it's gitingest's most recognizable
   visual signature, more than its specific color palette, and skipping
   it would leave the redesign looking generically "bordered" rather than
   actually gitingest-inspired.
3. **Brand accent colors (coral, amber) are scoped to chrome/branding
   only** — the logo, the primary CTA button, focus rings, the main
   panel's example-button styling. The event log's existing semantic
   palette (sky=tool_call, emerald/red=tool_result, violet=reasoning,
   amber=no_semantic_index — this one already amber, kept as-is since it
   predates this redesign and doesn't conflict) is **not** touched. Two
   different color systems for two different jobs: one identifies the
   product, the other identifies event types in a live log — conflating
   them would make the log harder to scan, undermining the product's own
   differentiator.
4. **A large title + subtitle is added above the form**, matching
   gitingest's pattern of stating the value proposition before asking for
   input, rather than the current minimal "coderag-mcp" heading alone.
5. **Inline help is always-visible text, not tooltips.** More
   discoverable (no hover required, works on mobile/touch), simpler to
   implement, and consistent with this project's existing preference for
   directness over progressive disclosure (e.g. the API key field is
   already a visible toggle, not hidden behind an icon).

## Visual design

**New shared primitive — `OffsetCard`:** a small wrapper component
(`frontend/src/components/OffsetCard.tsx`) implementing the
offset-shadow treatment once, reused everywhere it's needed, rather than
duplicating the two-div-plus-translate pattern per call site. Takes
`children` and an optional `className` for the visible panel; renders a
solid dark rectangle (`bg-black` or `bg-slate-950`, whichever contrasts
better against the actual panel background at each call site — decide
empirically during implementation, not fixed a priori) positioned via
`absolute inset-0 translate-x-1 translate-y-1` behind a `relative
z-10` panel with a `border-2 border-slate-100` (or similar
near-white/light border, since dark mode inverts gitingest's near-black
border into a near-light one for contrast against a dark page).

**Color tokens (new, additive to existing Tailwind classes — no config
file changes needed, arbitrary/existing Tailwind color utilities
suffice):**
- Brand coral: `text-rose-500` (logo accent, e.g. "code**rag**-mcp" with
  the middle segment in coral).
- Brand amber: `bg-amber-500` (primary CTA button background, replacing
  the current `bg-sky-600`), `focus:border-amber-400` (input focus
  state).
- Example buttons: `bg-amber-950 hover:bg-amber-900 border-amber-700`
  (warm, muted dark-mode equivalent of gitingest's tan/amber example
  buttons — exact shades decided during implementation by what reads
  clearly against `slate-950`, this is a starting point not a pixel-exact
  mandate).

**Applied to:**
- `App.tsx`: large bold title above the form (e.g. `text-4xl font-bold
  tracking-tight`), with the brand coral accent on part of the wordmark;
  a one-line subtitle beneath it in a muted tone (`text-slate-400`).
- `RepoForm.tsx`: the whole form wrapped in `OffsetCard`; the repo-URL
  input and submit button get `border-2`; the submit button becomes
  `bg-amber-500` instead of `bg-sky-600`; example buttons get the warm
  amber-toned treatment described above.
- `RunCard.tsx`: each card wrapped in `OffsetCard` (replacing its current
  plain `rounded border border-slate-800` treatment) with `border-2`.
- `EventLogLine.tsx`: no color changes (per decision 3) — this file is
  untouched by the visual redesign, only touched if the inline-help
  additions below land near it.

## Inline help copy

Three concrete additions (all always-visible text, per decision 5):

1. **API key field** (`RepoForm.tsx`): a small `text-xs text-slate-500`
   line beneath the field, shown whenever the field is expanded:
   *"Opcional — solo necesario si tu servidor tiene `CODERAG_API_KEY`
   configurada."*
2. **Event log preamble** (`RunCard.tsx`): one line above each card's
   event log, in the same muted tone as the existing "Conectando..."
   status text: *"Así explora y responde el agente, en vivo:"* — gives
   first-time viewers context for what the log means without requiring
   per-event-type explanations (the event types are already
   self-explanatory after yesterday's translation pass: "Indexando...",
   "✓ search_code: ...", "⚠ [no-index message]", etc.).
3. No other elements need new help copy — the repo URL/question fields
   have clear placeholders already, and the "no_semantic_index" warning
   (added in the previous plan) is already a complete, self-explanatory
   sentence in Spanish.

## Testing

- `OffsetCard`: a render test confirming it renders its children and
  applies the expected structural classes (two layered elements, correct
  z-index/positioning) — a pure presentational component, straightforward
  to test in isolation.
- `RepoForm`/`RunCard` tests: existing tests should keep passing
  unchanged (this is a styling/structural change, not a behavior change —
  no new user-facing text needs new selectors except the two new help
  lines, which get their own new assertions: one confirming the API-key
  helper text renders when the field is expanded, one confirming the
  event-log preamble renders in `RunCard`).
- No visual regression tooling (e.g. screenshot diffing) — out of scope,
  this project doesn't have that infrastructure and adding it now would
  be disproportionate to a styling pass. Manual browser verification
  (per this project's established practice for UI changes) substitutes.
- Full test suite (99 backend / 29 frontend at time of writing) must stay
  green — this plan touches frontend only, backend suite should be
  unaffected entirely.
