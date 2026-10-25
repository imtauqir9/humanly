# Article style lessons (from the FDA article teardown)

Source: [Forward Deployed Architect (FDA): From Customer Problems to End-to-End Technology Solutions](https://www.linkedin.com/pulse/forward-deployed-architect-fda-from-customer-problems-ali-khan-gqrke/), Ali Khan on LinkedIn. Reviewed 2026-10-19.

The article earns trust through explanatory diagrams, a skimmable structure, keyword-cluster headings and concrete nouns.

## What to copy

### 1. Diagrams that explain structure, not stock photos
The article uses six images, all diagrams:
- a dense architecture diagram as the cover
- concentric rings (clean/onion architecture)
- an overlapping Venn (UX, business, design)
- a user-story-map grid
- a colour-coded service-blueprint grid

Each shows how things relate, so the reader sees expertise before reading a word. Generic stock photos are a large part of what makes AI articles feel sloppy.

### 2. A skimmable three-layer structure
1. A one-paragraph definition at the top (featured-snippet bait).
2. About ten overview paragraphs, each opening with a **bold label:** followed by two or three sentences.
3. Numbered deep-dive sections (26 in the source).
4. A final "How it's different from X" section to capture "X vs Y" searches.

### 3. Every heading is a keyword cluster
Example H2: "Cybersecurity, Identity, Access Management, Zero Trust, Cryptography, and Privacy" covers six long-tail searches. The piece is part of a "universe/taxonomy" series, which builds topical authority and internal links.

### 4. Specific nouns instead of hype
Name real tools and standards (Kafka, OpenTelemetry, OPC UA, SCADA). No "game-changer", no rhetorical questions, no em dashes. Concrete entity names read as human and help entity-based SEO.

## What not to copy

- **Repeated template.** Nearly every section opens "A Forward Deployed Architect…" and closes "The goal/objective is to…". That repetition is an AI tell.
- **Borrowed diagrams with bad alt text.** Well-known diagrams, no credit, alt text "Article content". Bad for accessibility, image SEO and copyright. Make original diagrams with descriptive alt text.
- **No first-hand experience.** No story, example, table, TL;DR or FAQ. Add at least one real anecdote or worked example to win on E-E-A-T.

## Pipeline changes (made 2026-10-19)

| Step | Change |
| --- | --- |
| 4 · Outline | Intro opens with a definition (featured-snippet lead); keyword-cluster H2s; numbered H2s for taxonomies; a "How X differs from Y" section when there is a real neighbour; bold-label paragraphs for parallel items; one example per section |
| 4 · Outline | Diagrams are the main visuals: at least half of all visuals, one per Level 2 section where a structure is clearer drawn. `[IMAGE:]` only for real photos or screenshots of named things, never generic stock |
| 8.5 · Diagrams | New `venn` (2-3 overlapping sets) and `grid` (matrix / blueprint) shapes beside flow, cycle, layers and compare. Each diagram now gets a descriptive `alt` sentence instead of its title |
| 5 · Draft | Rules 16-19: definition lead, a concrete example and named tools per H2, bold-label paragraphs, no templated openers or closers, no rhetorical questions |
| 6 · Humanizer | Rule 15 now strips bold headers from bullets only and keeps bold-label paragraphs. New rules 25-27: templated openers, templated closers, rhetorical questions |
| 6 · Scanner | Flags the same three-word opener under 3+ headings, "the goal is to"-style closers, and question sentences in the body (headings and the FAQ are skipped) |
