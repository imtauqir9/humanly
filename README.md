# Humanly

**An AI agent that writes publication-ready SEO articles — and then argues with itself about them.**

You give it a topic and a goal. It does the research, writes the draft, strips the AI tells, and then hands the result to a second model on a different vendor whose only job is to find what's wrong with it. The writer gets to argue back. A third model settles what's still contested. Only what survives the argument reaches the file on disk.

The pipeline runs in 10 stages: live SERP research, title refinement, key takeaways, outline, writing, a three-pass humanization stage that strips AI patterns, a direct-answer block for answer engines, an adversarial verification stage where a second model audits the draft and the writer gets to argue back, meta description, and image sourcing. Three more optional stages write a LinkedIn post, a video script and a share card from the finished article. Everything is automated.

### See it

| | |
|---|---|
| **[Walk the whole flow →](docs/flow.html)** | Every screen, all ten stages, and the argument the three agents have — drawn out. Open it locally, or via [htmlpreview](https://htmlpreview.github.io/?https://github.com/imtauqir9/humanly/blob/main/docs/flow.html). |
| **[Read an article it wrote →](examples/)** | A full 3,000-word piece with its metadata, exactly as the pipeline produced it. Nothing was touched by hand. |
| **Run it yourself** | `pip install -r requirements.txt && python app.py` — then [localhost:8080](http://localhost:8080). |

<!-- SCREENSHOTS — drop three PNGs in docs/screenshots/ and uncomment. In order of impact:
     1. review.png    — /review/<slug>, the three voices arguing over one finding. Nothing else in this space has this.
     2. progress.png  — the live log mid-run, [STEP 6.5] Writer responding to 4 finding(s)
     3. form.png      — the generate form with the length dropdown and the three extras

![The three agents arguing over a finding](docs/screenshots/review.png)
![The pipeline running live](docs/screenshots/progress.png)
![The generate form](docs/screenshots/form.png)
-->

---

## What it does

- **Deep research first** — pulls live Google search results via SerpAPI before writing a single word. The agent reads what's ranking, identifies gaps, and builds the article around those findings.
- **Learns from your sample articles** — drop your best articles into `sample-articles/` and the agent uses them as style references, and builds a short *voice profile* from them (cached, rebuilt when they change) that every prose-touching step is held to. The output reads like you wrote it, not like ChatGPT.
- **Teaches in layers, with a diagram it draws itself** — every article opens with the simple version for a newcomer (analogy, example, terms defined, a real diagram), then climbs to how it works, then to where it gets hard. The diagram is rendered by the app, not searched for.
- **Finds real images** — searches Google Images (with SerpAPI) or Unsplash and embeds them directly into the DOCX. No placeholder images.
- **Humanization pass built in** — after writing, the agent rewrites the draft to remove AI patterns before you ever see it. The last pass is measured, not vibed: a scanner counts the tells that survived and hands the model the exact phrase list to repair.
- **The draft has to survive an argument** — a second model audits the finished article against the brief it was written from. The writer can dispute findings it thinks are wrong, a third model settles what stays contested, and only what survives gets applied.
- **Three roles, three sets of weights** — writer, auditor and judge are pushed onto the most distinct vendors your keys allow. The auditor moves off the writer's vendor first, because a blind spot shared between those two means the finding is never raised at all.
- **Ships SEO and GEO metadata, not just prose** — the HTML carries a real head (title, description, canonical, Open Graph, Twitter cards) plus `Article` and `FAQPage` JSON-LD built from the article's own FAQ. Citations render with a publisher name and access date, and a short extractable answer sits under the H1 for answer engines to quote.

---

## Pipeline

```
Topic + Intent
      │
      ▼
1. SERP Research      — pulls live Google results via SerpAPI, reads what's ranking
      │
      ▼
1.5 Fact pack         — opens the primary pages (vendor pricing, docs, exam guides,
      │                 first-party reports) with Claude's web search + fetch tools,
      │                 and pins every specific to a URL and a verbatim quote. The
      │                 writer may state no figure that is not in the pack, and may
      │                 not widen a pack value into a range. Saved as <slug>_facts.json.
      ▼
2. Title Refinement   — picks the best angle and target keyword
      │
      ▼
3. Key Takeaways      — identifies what the article must cover to outrank competitors
      │
      ▼
4. Outline            — structures the article in three levels: the simple version
      │                 (with a [DIAGRAM:] marker), how it actually works, where it
      │                 gets hard
      │
      ▼
5. Write              — full draft grounded in research, your sample articles and
      │                 the voice profile built from them
      │
      ▼
6. Humanize           — strips AI patterns, rewrites to match your voice
      │
      ├─► pass 1  pattern removal against a 24-item checklist
      ├─► pass 2  the model self-audits its own draft
      └─► pass 3  a scanner counts what actually survived — banned vocabulary,
      │           title-cased headings, inline-header bullets, em dashes,
      │           uniform sentence length — and the model repairs the named
      │           phrases only. If the count goes up, pass 2 is kept.
      ▼
6.2 Level 1 check     — measures the simple version's sentences (mean ≤ 17 words,
      │                 none over 30) and rewrites just that section if it is dense
      ▼
6.4 Answer block      — a 40–60 word extractable answer placed under the H1,
      │                 written to survive being quoted on its own
      ▼
6.5 Verify            — a second model audits the draft against the brief
      │
      ├─► audit    a different vendor scores factual support, outline fidelity,
      │            voice and coverage, returning findings anchored to quotes
      ├─► rebuttal the writer accepts or disputes each finding
      │            (silence counts as acceptance)
      ├─► judge    a third model rules on what is still contested
      └─► fix      only accepted and upheld findings are applied,
      │            then re-audit — up to 2 rounds
      ▼
7. Meta               — generates SEO title, meta description, and slug
      │
      ▼
8. Images             — finds real images via Google Images or Unsplash, embeds in DOCX
      │
      ▼
8.5 Diagram           — turns the Level 1 [DIAGRAM:] marker into a spec (flow, cycle,
      │                 layers or compare) and renders it: SVG inline in the HTML,
      │                 PNG in the Markdown and the DOCX. No browser, no fonts to install.
      │
      ▼
Output: .md  .html  .docx  _meta.json  _diagram_1.png/.svg
```

---

## Setup

### 1. Clone and configure

```bash
git clone <repo-url>
cd SEO-writer
cp .env.example .env
```

Open `.env` and add your keys:

```ini
ANTHROPIC_API_KEY=sk-ant-...   # required
SERPAPI_KEY=...                 # optional but recommended

# Step 6.5 roster. Each extra key buys a more independent audit.
OPENAI_API_KEY=sk-proj-...      # optional; moves the auditor off Anthropic
GEMINI_API_KEY=...              # optional; moves the judge off both
AUDITOR_PROVIDER=auto           # auto | anthropic | openai | gemini
JUDGE_PROVIDER=auto
OPENAI_JUDGE_MODEL=gpt-5.5
GEMINI_MODEL=gemini-2.5-pro

# Publication identity — canonical URL, og:url, Article/Person schema.
SITE_URL=https://yoursite.com/blog   # blank omits canonical rather than guessing
AUTHOR_NAME=Imran Tauqir
AUTHOR_URL=https://imrantauqir.com/
```

Which roles run where, by the keys you have:

| Keys present | Writer | Auditor | Judge |
|---|---|---|---|
| Anthropic only | `claude-sonnet-5` | `claude-opus-5` | `claude-opus-5` |
| Anthropic + OpenAI | `claude-sonnet-5` | `gpt-5.5` | `claude-opus-5` |
| Anthropic + OpenAI + Gemini | `claude-sonnet-5` | `gpt-5.5` | `gemini-2.5-pro` |

The writer always stays on Anthropic — the style prompts and sample-article matching were tuned against it, so swapping it changes the product rather than checking it. If a vendor is down mid-run, that role falls back to Claude and says so, because a vendor outage must not destroy an article that already cost a dozen calls.

### 2. Install dependencies

With `uv` (no setup needed):
```bash
uv run --with anthropic --with requests --with flask --with markdown --with python-docx app.py
```

With pip:
```bash
pip install -r requirements.txt
python app.py
```

Then open [http://localhost:8080](http://localhost:8080).

---

## CLI

```bash
# Basic
python seo_writer.py "What is RAG in AI"

# With intent — the agent figures out the right angle and keywords
python seo_writer.py "ReAct Agents" \
  --intent "explain to developers how ReAct agents think step by step"

# Custom output folder and edition number
python seo_writer.py "Semantic Caching for LLMs" --output-dir ./articles --edition 31
```

| Flag | Description |
|------|-------------|
| `topic` | What to write about (required) |
| `--intent` | What you want readers to take away — agent uses this to pick keywords and angle |
| `--keywords` | Explicit keywords if you already know what to target |
| `--output-dir` | Where to save output (default: `./output`) |
| `--edition` | Newsletter edition number |
| `--no-verify` | Skip the step 6.5 audit — faster and cheaper, but nothing checks the article's claims or structure before it hits disk |
| `--verify-rounds` | Maximum audit/fix rounds before accepting the article (default: `2`) |
| `--take` | Your own positions and experiences, one per line (or a path to a text file). Each is written into the article in first person and the auditor checks it survived. The run warns loudly when this is missing, because it is the single biggest reason an article reads as generic |
| `--no-facts` | Skip the Step 1.5 fact pack. The writer is then forbidden from stating any price, date, version or statistic |
| `--radar` | Don't write; find out what to write. See *Topic radar* below |
| `--radar-days` | How far back the radar looks (default `14`) |
| `--dig N` | Deep research on theme N of the latest radar: discussion threads, transcripts, public LinkedIn posts, practitioners' write-ups → a one-page brief |
| `--no-diagram` | Skip the Step 8.5 diagram. The `[DIAGRAM:]` marker in the Level 1 section is dropped instead of drawn |
| `--words` | Article length: `default` (2,500–3,500), `2000`, or `1000` |
| `--linkedin` | Also write a LinkedIn post from the finished article |
| `--video` | Also write a 2–3 minute video script, timed, with a visual per beat |
| `--voiceover` | Also record that script's narration in your own cloned voice (ElevenLabs) as `<slug>_voiceover.mp3`. Implies `--video`; needs `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` |
| `--thumbnail` | Also design a LinkedIn share card, with a button to save it as a PNG |
| `--audit FILE` | Audit a document you already have instead of writing a new one |
| `--apply` | With `--audit`, also save the revised document |

---

## What makes it yours: the author's take

The pipeline can research, structure, humanize and verify, but it cannot know
what you think. `--take` (or the "Your take" box in the web form) is where that
goes: three to five lines of your own positions and experience on the topic.

```bash
python seo_writer.py "NVIDIA AI certification guide" \
  --intent "help engineers pick the right track and budget for it" \
  --take "I took the DLI CUDA workshop; the graded lab is harder than the exam guide implies.
The networking track is underrated: few people hold it and DGX shops need it.
Skip the Associate exam if you already have a year on GPU clusters."
```

Each line is written into the article in first person, in the section where it
belongs, and the Step 6.5 auditor flags any that went missing or got neutralised
into a hedge. Without a take, the run prints a warning and produces what it can:
a well-sourced summary of what everyone else already wrote.

Two related fixes shipped with this: the writer now actually receives its system
prompt (it was built and never sent), and the sample articles in
`sample-articles/` are now actually loaded as style exemplars (the README said
they were; the code did not do it).

---

## Topic radar: what should I write?

The pipeline writes whatever topic it is handed. The radar answers the question
before that one. Press **Run the radar** in the app (or `python seo_writer.py
--radar`) and one research pass reads the last two weeks of the AI industry's
conversation:

| Source | How it is read |
|---|---|
| YouTube — the most-watched AI videos and the big channels | Claude's web search + fetch, with the view counts the pages show |
| Podcasts — Latent Space, Lex, No Priors, a16z, Practical AI, Dwarkesh, … | same |
| Newsletters and posts — Simon Willison, Karpathy, Mollick, swyx, Hamel Husain, The Batch, … | same |
| Hacker News | the Algolia API, free, no key |
| Reddit — r/LocalLLaMA, r/MachineLearning, r/artificial, … | the RSS feeds, best effort (Reddit rate-limits them) |
| LinkedIn — public posts and articles by AI practitioners | web search (`site:linkedin.com/posts`, `/pulse`); only pages that open without login |

The signals are clustered into **up to eight themes**, each needing at least
two independent sources, and scored on breadth, heat, freshness and — most
heavily — the **gap**: whether the sources already treat it the way an engineer
who ships would. A theme everyone is covering well scores low. For each theme
you get why it is live now, who is talking, the angle your readers need that
nobody is giving, a working title, an intent, and two or three first-person
takes to edit. Every evidence link is one the radar actually saw; it cannot
cite a URL it did not open or find.

**Write this** on a theme fills the form — topic, intent, take — and the normal
pipeline takes it from there. Results are saved as `radar_<date>.md` and
`.json`, and `radar_latest.json` is what the app shows on load.

**Weekly.** Set `RADAR_WEEKLY=mon` (any day) and the deployed app runs it on
that day whenever the last radar is more than six days old; the result waits in
the app. Set `RADAR_CALLBACK_URL` too and it is POSTed there (Zapier, n8n) with
the themes inline and signed links to the files. `POST /api/radar` with a
`callback_url` does the same on demand. `RADAR_LENS` describes who you write
for; it steers what counts as a gap.

**Dig in.** The radar knows *what* people are talking about; it has not read
the arguments. **Dig in** on a theme (or `--dig N`) reads them: the Hacker News
comment threads (by API), the Reddit threads (feeds, when they answer), the
episode and video transcripts, public LinkedIn posts and articles, and
write-ups by people who actually built the thing. It returns a one-page brief
— `radar_<date>_brief_N.md` — with the strongest claims and verbatim quotes,
the pushback, what practitioners reported, every number with its source, the
questions nobody answers, and a sharper angle, title, intent and takes.
The brief attaches to the theme, so **Write this** uses it. About $2–3 and
five minutes per theme.

A radar run costs about $1–1.50 (most of it is reading the pages) and takes three to five minutes. Reddit rate-limits its feeds, so some subreddits are skipped on a given run; the radar says which.

---

## Teach in layers, with a diagram the app draws

A flat article pitches every section at the same reader, which is nobody. Every
article now climbs three levels, and the outline, the writer and the auditor all
hold to the shape:

| Level | Who it is for | What it must contain |
|---|---|---|
| 1 — The simple version | Someone smart who has never met the topic | One everyday analogy, one concrete example, every term defined in plain words on first use, sentences mostly under 15 words, and the diagram |
| 2 — How it actually works | A practitioner | The moving parts, the numbers from the fact pack, the comparison table, the tradeoffs |
| 3 — Where it gets hard | Someone who has done it | What experienced people argue about, where it breaks, what you have seen first-hand — most of `--take` lands here |

Level 1 is checked by measurement, not by asking: if its sentences average more
than 17 words or any runs past 30, that one section is rewritten before the
auditor sees it. The auditor then has a `layering` category of its own — jargon
left undefined in Level 1, or a Level 3 that never rises above a beginner's guide.

**The diagram.** The Level 1 section carries one marker,
`[DIAGRAM: <title> | Shows: <the one thing the picture must make obvious>]`.
After verification, Claude turns it into a small structured spec — a `flow` of
steps, a `cycle`, stacked `layers`, or side-by-side `compare` columns; never
free-form drawing — and the app renders that spec itself: an SVG inlined in the
HTML (crisp at any width) and a PNG for the Markdown and the DOCX. It needs only
Pillow, which ships its own scalable font, so it works on Fly's slim image with
nothing else installed. A stock photo next to "the simple version" explained
nothing; this shows the mechanism.

**Your voice, described.** The sample articles were only ever shown to the
writer, and only as raw text. On first run the app reads them once and writes a
short voice profile — sentence rhythm, how the reader is addressed, how terms
are handled, what you never do — cached at `sample-articles/.voice_profile.json`
and rebuilt when the samples change. That profile now goes to every call that
touches the prose: writer, both humanizer passes, the Level 1 rewrite, the fix
pass, and the auditor, which flags passages that read nothing like it.

---

## Length and the LinkedIn post

`--words` takes `default`, `2000` or `1000`, and the dropdown in the web form
does the same thing. Length is not a single instruction: telling the writer
"1,000 words" while the outline still demands seven sections, eight images and
five FAQ questions produces a cramped article rather than a short one. So every
structural number moves together.

| | Default | 2000 | 1000 |
|---|---|---|---|
| Words | 2,500–3,500 | 1,800–2,200 | 900–1,100 |
| H2 sections | 5–7 | 4–6 | 3–4 |
| H3 per section | 2–3 | 2 | 1–2 |
| Images | 6–8 | 4–5 | 2–3 |
| FAQ questions | 4–5 | 4 | 3 |

`--linkedin` writes `<slug>_linkedin.md` alongside the article. The post is
generated **from the finished, verified article** rather than from the brief, so
it can only claim things the article actually established — a post written from
the topic alone is free to invent a statistic the article never supports.

It is written to the constraints that actually matter on the platform: 150–220
words, the first two lines carrying the whole post because that is all LinkedIn
shows before "see more", one idea per line, no engagement bait, no em dashes,
and at most three specific hashtags.

`--video` writes `<slug>_video.md`: a 2–3 minute script as six timed beats —
hook, core idea, why it matters, the substance, the distinction, what breaks —
each with the **visual that carries it**, then a narration-only block at the end
ready to paste into a teleprompter or a text-to-speech tool.

The visual note is the part that matters. The failure mode of an AI-written
script is a spoken list of abstractions that no footage can illustrate, so the
prompt requires something actually showable — a diagram that builds, text on
screen, a comparison filling in — and explicitly rejects "stock footage of a
developer typing", which illustrates nothing. Runtime is measured from the
narration alone, not the document, since headings and visual notes are not
spoken.

---

## Password protection

`POST /api/start` spends real money — roughly fifteen model calls across three
vendors, two of them at high effort. Deployed without a password it is an open
faucet on your card, so set one anywhere the app is reachable from the internet:

```bash
APP_PASSWORD=something-long     # in .env, or as a Fly secret
APP_USERNAME=admin              # optional, defaults to admin
```

Every route is then behind HTTP basic auth, including the JSON APIs. Two
exceptions by design: `/healthz` stays open so a health check doesn't need a
credential, and leaving `APP_PASSWORD` blank leaves the app open — which is fine
on localhost and is not fine on a public URL.

```bash
flyctl secrets set APP_PASSWORD='something-long' -a your-app
```

`GET /healthz` reports `{"ok": true, "protected": true|false}`, so you can check
from the outside whether the deployed app is actually locked.

---

## Starting runs from Zapier, n8n or a script

The browser follows a run over a live event stream, which an automation
platform cannot hold open for ten minutes. So `POST /api/start` takes an
optional `callback_url`: when the pipeline exits, the app POSTs one JSON
payload there, and echoes your `external_id` so you can find your own record.

```bash
curl -u admin:$APP_PASSWORD https://your-app.fly.dev/api/start \
  -H 'Content-Type: application/json' \
  -d '{
    "topic": "Semantic caching for LLM apps",
    "intent": "convince platform engineers it is worth the infra cost",
    "words": "2000",
    "linkedin": true, "video": true,
    "callback_url": "https://hooks.zapier.com/hooks/catch/…",
    "external_id": "recAIRTABLE123"
  }'
# → {"job_id": "…", "external_id": "recAIRTABLE123"}
```

The callback payload:

| Field | What it is |
|---|---|
| `status` | `done` or `error`; `error` carries the message |
| `external_id`, `job_id`, `request` | What you sent, echoed back |
| `slug`, `meta`, `images`, `word_count` | SEO title, description, slug and the image list from `_meta.json` |
| `article_md`, `linkedin_md`, `video_script_md` | The article and the extras, inline |
| `files` | Download links for `md`, `html`, `docx`, `meta`, `linkedin`, `video`, `voiceover`, `thumbnail`, `review_md`, `review_json`, `facts`, `diagram_png`, `diagram_svg`, `usage` |
| `usage` | Calls, tokens and cost for this run |

The links in `files` go through `/dl/<expiry>/<signature>/<file>` — signed
with an expiring HMAC, so the receiver fetches finished files without the app
password. They are built from `PUBLIC_URL` (set it on Fly), and expire after
`DOWNLOAD_TTL_SECS` (default seven days). Delivery retries three times with
backoff; the outcome is in the server log under `[callback]`.

On Fly, keep `min_machines_running = 1` in `fly.toml`: a run started this way
has no browser connection holding the machine awake, and scale-to-zero would
stop it mid-job.

---

## Token usage

Every run appends a line to `output/usage.jsonl` and writes a per-article
`<slug>_usage.json`. **`/usage`** renders it: totals, cost per article, a
per-model breakdown and a per-day history.

Token counts come from what each API actually reports — `usage.input_tokens` and
`usage.output_tokens` on Anthropic, `prompt_tokens`/`completion_tokens` on
OpenAI, `usage_metadata` on Gemini. They are counted, never estimated.

Cost is a softer layer. The built-in table carries Anthropic's first-party list
prices (`claude-sonnet-5` $2/$10 per MTok, `claude-opus-5` $5/$25). **A model
with no price on file still has its tokens counted and simply reports no dollar
figure** rather than a wrong one — the dashboard flags those runs and treats the
total as a floor. Add your own rates rather than trusting a guess:

```bash
MODEL_PRICES={"gpt-5.5": [1.25, 10.0], "gemini-2.5-pro": [1.25, 10.0]}
```

The CLI prints the same summary at the end of every run:

```
  Tokens: 184,203 in + 27,410 out = 211,613 across 17 calls
    claude-sonnet-5       11 calls   120,400 in   19,900 out  $0.440
    claude-opus-5          4 calls    48,100 in    6,200 out  $0.396
    gpt-5.5                2 calls    15,703 in    1,310 out  unpriced
  Estimated cost: $0.84 plus unpriced models
```

---

## SEO and GEO

The `.html` export is meant to be pasted into a CMS as-is, so the metadata the
pipeline computes actually ships with it rather than sitting in a sidecar JSON
file no crawler will read.

**In the head:** `<title>`, meta description, `lang`, viewport, author, canonical
(only when `SITE_URL` is set — a wrong canonical is worse than none), Open Graph,
and Twitter card tags.

**Structured data:** an `Article` node with `datePublished`, `wordCount`, author
and publisher as a `Person`, the article's images, and every source as a named
`citation`. When the article has a FAQ section, a `FAQPage` node is built from it
— which is why the outline requires FAQ questions to be H3s ending in a question
mark, and answers that stand on their own. Anything that isn't a real question is
skipped rather than shipped as malformed data.

**For answer engines specifically:**

| | What it does |
|---|---|
| Answer block | 40–60 words directly under the H1, written to make sense quoted with no surrounding page. Generated *before* verification, so the auditor fact-checks it like any other passage. |
| Named citations | `IDC — https://idc.com (accessed September 02, 2026)` rather than a bare URL. Attributable citations are weighted; naked links aren't. |
| Comparison table | The outline requires one where the topic genuinely has something to compare. Tables are the passage most often quoted whole. |
| FAQ pairs | Question-shaped headings match how people actually query an assistant. |

Set `SITE_URL` before publishing. Without it the canonical, `og:url` and schema
`mainEntityOfPage` are all omitted.

---

## Auditing your own writing

The three agents don't only work on articles this tool wrote. Point them at any
document and they'll argue about it.

**In the browser:** open the app, switch to the **Evaluate a draft** tab, and
either upload a `.md`/`.txt`/`.docx` or paste the article in. The live log runs
as it does for generation, and the finished report opens as a page showing every
finding with all three voices on it. Reports stay available at `/review/<slug>`.

**From the CLI:**

```bash
# Analyse a document you already have — no article, images or meta are generated
python seo_writer.py --audit ./drafts/my-post.md

# Name the topic so the report and filenames read properly, and tell the auditor
# what you were going for
python seo_writer.py "Semantic caching for LLMs" \
  --audit ./drafts/my-post.md \
  --intent "convince platform engineers this is worth the infra cost"

# Also write out the corrected version
python seo_writer.py --audit ./drafts/my-post.md --apply
```

The auditor works by comparing an article against the brief it was written from,
and a file you hand it has no brief. So one call first reconstructs the brief the
document *appears* to be written to — its own heading structure and the points it
promises the reader — and the agents argue against that. `--intent` feeds your
actual goal into that reconstruction, which makes the coverage findings sharper.

You get back `<slug>_review.md`: the roster, the per-round scores, and every
finding with all three voices on it.

```
### i3 - factual (high)

> cuts p99 latency by roughly 40%

**Auditor:** No citation, and the figure is presented as general fact. _Wants:_ Attribute it or cut it.
**Writer:** disputed. The source is cited two paragraphs down.
**Judge:** uphold. The citation two paragraphs down covers a different claim.

**Result:** applied
```

---

## Output

Each run produces these files in `./output/`:

| File | What it is |
|------|------------|
| `<slug>.md` | Full article in Markdown |
| `<slug>.html` | Styled HTML, ready to copy into a CMS |
| `<slug>.docx` | Word document with embedded images |
| `<slug>_meta.json` | SEO title, meta description, slug, image URLs |
| `<slug>_facts.json` | The fact pack the article was held to: every figure with its source URL and quote, plus the gaps no source filled |
| `<slug>_diagram_1.png` / `.svg` | The Level 1 diagram, drawn by the app. The PNG is what the Markdown and DOCX embed; the SVG is inlined in the HTML |
| `<slug>_review.md` | What the three agents argued about, and what survived |
| `<slug>_review.json` | The same argument as raw data |
| `<slug>_linkedin.md` | LinkedIn post, with `--linkedin` |
| `<slug>_video.md` | Video script, with `--video` |
| `radar_<date>_brief_N.md` / `.json` | The dig-in brief for theme N: claims with quotes, pushback, practitioner reports, numbers, LinkedIn, open questions |
| `radar_<date>.md` / `.json` | The topic radar: ranked themes with evidence, angle, title, intent and takes. `radar_latest.json` always points at the newest |
| `<slug>_voiceover.mp3` | The script's narration, spoken in your cloned voice, with `--voiceover` |
| `<slug>_thumbnail.html` | Share card, with `--thumbnail`. Open it and click to save a PNG |
| `<slug>_usage.json` | Tokens and cost for this run, per model and per step |
| `usage.jsonl` | One line per run — the rolling log behind `/usage` |

An `--audit` run writes only the two review files, plus `<slug>_revised.md` if you
passed `--apply`.

---

## Project structure

```
humanly/
├── seo_writer.py       # Core agent + CLI — the whole pipeline lives here
├── app.py              # Web UI (Flask): jobs, streaming log, auth, usage
├── requirements.txt
├── .env.example        # Copy to .env and fill in keys
├── templates/
│   ├── index.html      # The form, the live log, the article library
│   ├── review.html     # /review/<slug> — the argument, with all three voices
│   ├── deck.html       # /deck/<slug> — the video script as timed slides
│   ├── usage.html      # /usage — tokens and cost
│   └── login.html
├── docs/flow.html      # End-to-end walkthrough of how a run works
├── examples/           # A real article the pipeline produced, untouched
├── sample-articles/    # Your reference articles — agent uses these for style
└── n8n/                # Original n8n workflow this was built from
```

---

## Keys

| Variable | Required | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | Yes | [console.anthropic.com](https://console.anthropic.com/) |
| `SERPAPI_KEY` | No | [serpapi.com](https://serpapi.com/) — enables live research and real images |
| `SITE_URL` | No | Your blog's base URL. Enables canonical, `og:url` and schema `mainEntityOfPage` |
| `AUTHOR_NAME` | No | Author in the head and the Article/Person schema |
| `AUTHOR_URL` | No | Author profile URL used in the schema |
| `OPENAI_API_KEY` | No | [platform.openai.com](https://platform.openai.com/api-keys) — moves the step 6.5 auditor off Anthropic |
| `GEMINI_API_KEY` | No | [aistudio.google.com](https://aistudio.google.com/apikey) — moves the judge off both. Needs `pip install google-genai` |
| `AUDITOR_PROVIDER` | No | `auto` \| `anthropic` \| `openai` \| `gemini` |
| `JUDGE_PROVIDER` | No | Same values as above |
| `OPENAI_JUDGE_MODEL` | No | Default `gpt-5.5` — set to a model your key can reach |
| `GEMINI_MODEL` | No | Default `gemini-2.5-pro` — set to a model your key can reach |
| `APP_PASSWORD` | No | **Set it on any public deployment.** Enables HTTP basic auth on every route |
| `APP_USERNAME` | No | Username for that auth, default `admin` |
| `MODEL_PRICES` | No | JSON `{"model": [in_per_mtok, out_per_mtok]}` to price models the built-in table doesn't cover |
| `PORT` | No | Web server port, default `8080` |
