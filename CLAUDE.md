## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

## Research notes
`research/` holds the author's own sourced research: a ranked report at the top
level and, under `research/notes/`, the dated notes behind it with a URL on
every claim. Finished pieces written from them live in `articles/`.
- When writing or editing an article from this material, facts come only from
  `research/` or the run's fact pack. Nothing from memory.
- Keep every `[VERIFY]`, "secondary source" and "vendor claim" marker as it
  stands. A flagged number is never written as fact: check it at its URL first
  or leave it out.
- To run the pipeline on the notes:
  `python seo_writer.py "<title>" --intent "<angle>" --notes research/notes`
  (add `--no-facts` to skip the web pass and use the notes alone, and
  `--resolve-gaps` to have an agent open the page behind every flagged claim
  and settle it before the draft is written).
