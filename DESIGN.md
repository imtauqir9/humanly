# Design System — Humanly

## Product Context
- **What this is:** A private AI writing pipeline. You brief an article with your own first-person take; a topic radar suggests what to write; the pipeline researches, drafts, and runs a three-agent audit (auditor, writer, judge); the library holds every artifact it produced.
- **Who it's for:** One author (Imran Tauqir) writing technical articles, LinkedIn posts and videos.
- **Space/industry:** AI writing tools, but deliberately not styled like one.
- **Project type:** Internal web app (Flask + Jinja, `templates/`).

## Aesthetic Direction
- **Direction:** Writer's studio. Editorial / magazine with refined restraint.
- **The one thing to remember:** *Written by a human, checked by an editor.* Manuscript paper, a literary serif, a typewriter for the machine, and one red pen that marks what matters.
- **Decoration level:** Intentional. A faint paper grain on the page background, hairline rules, small-caps section labels, italic roman numerals. No gradients, no glows, no purple.
- **Preview:** `~/.gstack/projects/seo-writer/designs/design-system-20260929/preview.html`

## Typography
- **Display:** Fraunces (variable, `opsz` 9–144), weights 300–500. Page titles, card/section headings, article and radar-theme titles, numerals. Italic for emphasis and marginalia.
- **UI / body:** Instrument Sans 400/500/600. Labels, buttons, form text, descriptions.
- **Data / log / code:** IBM Plex Mono 400/500. Run log, timestamps, token counts, costs, dates in margins. Always `font-variant-numeric: tabular-nums` for numbers.
- **Section labels:** Instrument Sans 11px / 600 / uppercase / letter-spacing .14em, preceded by an italic Fraunces roman numeral in vermilion (`i.`, `ii.`, `iii.`).
- **Loading:** Google Fonts, one `<link>` in `templates/_head.html`.
- **Scale:** 11 (labels) · 12.5 (meta) · 14.5 (body) · 17–19 (list titles, serif) · 24–28 (panel titles, serif) · 40–52 (page titles, serif, opsz 144).

## Color
- **Approach:** Restrained. Neutrals carry the page; the vermilion is rare and always means "the editor's mark" (primary action, active nav, first rank, strikes, stamps).

| Token | Light | Dark ("night desk") | Use |
|---|---|---|---|
| `--bg` paper | `#FBF9F5` | `#171512` | Page background (with grain) |
| `--surface` sheet | `#FFFFFF` | `#201D19` | Cards, form sheet |
| `--surface-2` | `#FDFBF8` | `#25221D` | Hover, headers, margins |
| `--sunken` well | `#F4F0E9` | `#2B2722` | Chips, segmented controls |
| `--ink` | `#26231F` | `#ECE6DA` | Primary text |
| `--ink-2` | `#57524A` | `#C9C1B3` | Secondary text |
| `--muted` pencil | `#8A8276` | `#948B7D` | Meta, hints |
| `--faint` | `#C2BBAF` | `#6A6358` | Placeholders, idle numerals |
| `--line` rule | `#EEE9E0` | `#332E28` | Hairlines |
| `--line-2` | `#E2DBCF` | `#3F3931` | Input borders |
| `--accent` vermilion | `#D2553A` | `#E06A4E` | Primary action, active, marks |
| `--link` ink-blue | `#2F5288` | `#9DB6DA` | Links, focus ring, "running" |
| `--ok` moss | `#4E7A45` | `#8DBA7F` | Success, low saturation |
| `--warn` ochre | `#B07A1E` | `#E0B25E` | Warnings |
| `--bad` oxblood | `#962A20` | `#E7877A` | Errors (always with an icon, so it never reads as the accent) |

- **Dark mode:** a warm charcoal desk, never blue-black; vermilion lifted, saturation eased. Follows the system setting; the header toggle overrides and is remembered.

## Spacing
- **Base unit:** 4px. **Density:** comfortable.
- **Scale:** 4 · 8 · 12 · 16 · 20 · 24 · 32 · 48 · 64.

## Layout
- **Approach:** Hybrid. Editorial headers and room for titles; strict grid for data.
- **Write:** brief sheet (≈520px) left, the desk (run, radar, recent) right; single column under 1040px.
- **Library:** an editorial index, not a card grid: number · date in the margin · serif title, description, small-caps artifact links · stats right.
- **Max width:** 1320px. Side gutter 28px desktop, 12–16px phone.
- **Radius:** 4 (chips, stamps) · 6 (inputs, buttons) · 10 (sheets). Never pill-shaped buttons.
- **Rules over boxes:** separate list items with hairlines; panel titles sit on a 2px ink rule.

## Motion
- **Approach:** Intentional, small moments of craft.
- Log lines ink in (fade + slight unblur, 400ms). Links draw their underline on hover (250ms). List rows warm on hover. The run status is a stamp: "Writing" breathes while running; "Done" lands slightly rotated.
- **Easing:** ease-out for enter, ease-in-out for moves. Respect `prefers-reduced-motion`.

## Signature patterns
- **Red pen:** skipped radar themes are struck through in vermilion; review findings show the quoted passage, and the auditor / writer / judge speak as margin notes (vermilion / ink-blue / ink).
- **Stamps:** mono uppercase text in a 1.5px border, used for run state and review outcome.
- **Wordmark:** `Human` in Fraunces with an italic vermilion `ly`.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-09-29 | Initial design system created | /design-consultation, "writer's studio" direction chosen by the user over mission-control and calm-premium |
| 2026-09-29 | Palette lightened | User asked for lighter colours: paper #FBF9F5, white sheets, brighter vermilion #D2553A |
