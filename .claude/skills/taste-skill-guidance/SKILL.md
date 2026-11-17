---
name: taste-skill-guidance
description: "Use when a page or section looks generic, templated, or 'AI-made' and needs real photographs, real icons, proper section rhythm, and hover/motion polish instead of SaaS-template defaults. Heavily distilled, prose-only excerpt of tasteskill (github.com/Leonxlnx/taste-skill, MIT) — the original skill's headless-browser build pipeline, finish gate, and Claude Code Stop hook were deliberately left out of this sandbox; this keeps only its design rules as reading material, not an enforced workflow."
---

# Taste — design rules (guidance only, not enforced)

This is a distillation of tasteskill's house rules and checklist, adapted as plain guidance for
tweaking an existing site. It does not run any scripts, does not require Chrome/Node, and does not
block completion on a "gate" the way the original skill does — treat it as a checklist to read and
apply by eye, not a tool to invoke.

## House rules

1. **No caption or description under any image, render, or visual.** Credits (if any) go in one footer line.
2. **Every visual actually renders** at common widths (roughly 1440, 1024, 768, 390px) — never an empty/broken state.
3. **One section per screen roughly:** the hero alone on the first screen; most sections one or two screens tall; no section heading peeking in early from the next section.
4. **Equal left and right content edges** — nothing bleeds to one side while the rest of the page is contained.
5. **Hover micro-animations, used consistently:** a linked card lifts ~2px, a photo zooms ~1.02–1.03x inside its frame, buttons step on hover and press on click, underlines draw in. No tilt, no carousels, no timed auto-rotating tabs.
6. **Real photographs over stock-feeling placeholders** where the content allows it; better heroes, layouts, and fonts generally beat "safe" ones.
7. **Real, full-color icons** (an actual product's real icon) rather than generic line-icon placeholders when referencing a specific tool/brand.
8. **Match intensity to the subject.** Big award-site scenes and shader/creative effects belong on tech/AI/gaming/developer-tool pages — never bolt them onto a local service or simple business page, which should lean on photographs instead.
9. **Keep fake contact details obviously fake in drafts** (street/district only, no real phone format, `.example` domains) until real client details are supplied.

## Never

- A card, row, or tile that fades in on scroll; a fade-in applied to every section uniformly; parallax on text; scroll-jacking; random blinking.
- Stock photographs passed off as the client's real product, people, or place.
- A drawn look-alike of a real logo; invented reviews, quotes, customers, or figures.
- Violet or lavender as an accent/ground/gradient color choice by default (it reads as an AI-generated-page tell) — a real third-party logo keeps its own colors.
- Copying a reference site's code, copy, pictures, or signature effect wholesale.

## Checklist (read with your eyes, not a script)

- **First screen** says plainly what is sold / who it's for, with one concrete fact; the hero fills the viewport at every width; its main action is inside it.
- **One section per screen**, heading first, nothing sparse or half-empty, no neighboring section's heading or image bleeding into view.
- **Equal edges**, no sideways scroll, nothing hanging off one side only.
- **No caption explains or apologizes for a picture.**
- **The right intensity for the subject** — effects/scenes only where the trade is genuinely technical; otherwise photographs, flat color, type, and real icons.
- **Motion**: every interactive element visibly answers hover/press; nothing tilts; one or two "dealt moments" total, not an effect on every section.
- **One consistent system**: one button style, one card style, one radius scale, one link treatment throughout — not several competing patterns left over from different redesign passes.
- **Copy**: headings name things, buttons are a verb + object, no leftover placeholder/lorem text, no generic "slop" phrasing.
- **Accessibility basics**: visible keyboard focus, alt text on images, heading order makes sense, tap targets ≥44px on mobile.
