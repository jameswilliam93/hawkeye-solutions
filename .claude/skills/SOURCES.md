# Design skills library — sources

Vendored into this sandbox worktree only (branch `sandbox/design-skills`), not into `main`.
None of these run installers, binaries, telemetry, or background hooks — they're markdown
guidance only, placed directly as Claude Code project skills.

| Skill folder | Source | License | Commit | Adapted? |
|---|---|---|---|---|
| `frontend-design/` | github.com/anthropics/skills (skills/frontend-design) | Apache-2.0 | 2c5958ecac7c | No — used as-is |
| `emil-design-eng/` | github.com/emilkowalski/skills (skills/emil-design-eng) | MIT | f7ce8c02d6e3 | No — used as-is |
| `impeccable-guidance/` | github.com/pbakaus/impeccable (skill/) | Apache-2.0 | b4bff1626c34 | Yes — stripped the CLI/binary setup step, `live`/`generate`/`hooks`/`pin`/`doctor` commands, and native iOS/Android material. Kept: core principles, modes, and the critique/polish/bolder/quieter/colorize/typeset/layout reference docs plus craft-floor.md. |
| `taste-skill-guidance/` | github.com/Leonxlnx/taste-skill (skills/taste-skill) | MIT | f6b76575f949 | Yes, heavily — the original is a full build pipeline requiring Node 22+, headless Chrome, a "finish gate" that blocks completion, and a Claude Code `Stop` hook that auto-runs on every session end. All of that was deliberately left out. Only the prose house rules, "never" list, and checklist survive, as read-it-yourself guidance rather than an enforced tool. |

## Why two of these look different from the real repos

`impeccable` and `taste-skill` are both large tools built around running their own scripts
(screenshot diffing, headless-browser QA, a hook that fires automatically when a Claude Code
session stops). Installing those for real would mean running their `npx` installers, which pull
in binaries, telemetry, and in taste-skill's case a hook that runs on every session end — more
than this sandbox experiment called for. The two official, self-contained skills
(`frontend-design`, `emil-design-eng`) needed no changes.

If an adapted skill turns out useful and you want the real thing (e.g. Impeccable's automated
`/audit` and slop-detector, or taste-skill's browser-verified build), that's a separate, explicit
decision — install via their own instructions, not through this sandbox.
