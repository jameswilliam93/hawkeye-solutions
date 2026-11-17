---
name: impeccable-guidance
description: "Use when polishing, critiquing, or tweaking the look of an existing frontend page or component: hierarchy, spacing, typography, color, motion, and catching generic 'AI-made' defaults. Adapted, markdown-only excerpt of the Impeccable design skill (github.com/pbakaus/impeccable, Apache-2.0) — the binary/CLI parts (scripts/impeccable, live mode, hooks) were deliberately left out of this sandbox; only the review/polish guidance is included."
---

This skill gives you the tools and permission to make design that earns the name out-of-distribution
craft. Work as an award-winning design director would: production-grade code, a clear POV, a deep
grasp of what the client and its users need, and exceptional craft.

Core principles:
- Finish the job. No hedging, no shortcuts: the deliverable is complete, except assets the user must provide.
- Scale ambition to the surface's mode (see Modes below).
- Verify by looking at the rendered result at the sizes it ships at, and batch the checks: fix what
  one look shows before looking again, rather than screenshotting after every tweak.

## How to design

- **The brief wins.** Honor pinned aesthetics, eras, materials, fonts, and palettes even when they
  conflict with a saturated-pattern warning. Redirecting a clear brief toward your own taste is failure.
- **Refinement preserves; redesign replaces.** Refinement keeps the incumbent identity, behavior,
  copy, and everything outside scope. Ask before replacing factual copy or adding claims. Redesign
  treats the old look as evidence/anti-reference. For this sandbox, default to **refinement** unless
  the user explicitly asks for a redesign.
- **Visual authority is evidence, not a filename.** A missing design-system doc alone doesn't make a
  project greenfield — look at the actual rendered site before deciding what to change.

## Modes

Name the mode from what the visitor's success looks like on this surface:

- **Persuade:** the visitor decides and acts (landing pages, marketing, pricing). Earn attention and action.
- **Operate:** the visitor completes a task (app UI, dashboards, forms). Scanability and consistency outrank expression.
- **Read:** the visitor understands something (docs, articles). Structure for comprehension.
- **Experience:** the visitor is inside the work itself (portfolios, galleries).

A tool's landing page is still Persuade; its own docs are still Read.

## Before any UI edit

Read [reference/craft-floor.md](reference/craft-floor.md) first — it carries the quality floor, the
absolute bans on common "AI slop" tells, and the reflexes no automated checker catches. Load it for
any actual edit; skip it for planning-only discussion.

## Commands (vendored subset)

Only the markdown-guidance commands were brought into this sandbox — the ones that depend on the
`impeccable` CLI binary (`live`, `generate`, `extract`, `document`, `init`, `doctor`, `hooks`, `pin`,
native iOS/Android audit) are not available here.

| Command | Use it for | Reference |
|---|---|---|
| `critique` | UX design review with heuristic scoring | [reference/critique.md](reference/critique.md) |
| `polish` | Final quality pass before shipping | [reference/polish.md](reference/polish.md) |
| `bolder` | Amplify a bland/safe design | [reference/bolder.md](reference/bolder.md) |
| `quieter` | Tone down an overstimulating design | [reference/quieter.md](reference/quieter.md) |
| `colorize` | Add strategic color to a monochromatic UI | [reference/colorize.md](reference/colorize.md) |
| `typeset` | Improve typography hierarchy and fonts | [reference/typeset.md](reference/typeset.md) |
| `layout` | Fix spacing, rhythm, and visual hierarchy | [reference/layout.md](reference/layout.md) |

When the user doesn't name a command, treat the request as general design work: read the relevant
reference file(s) above for what they're asking about, and craft-floor.md regardless.
