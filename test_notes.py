"""Step 1.4 harness: the author's research notes as a fact pack, with the model
call stubbed, so the loading, the [VERIFY] routing, the merge order and the
digest the writer sees can be checked without an API call.

Run:  python test_notes.py
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

import seo_writer as sw

NOTE_A = """# AI networking trends

Summary: AI back-end switch sales passed front-end sales in Q2 2026.

- [3 Sep 2026] Dell'Oro: AI back-end switch sales surpassed front-end sales for the first time. — [Dell'Oro](https://www.delloro.com/news/x)
- Arista names its 1.6T platform 7060XE7 [VERIFY model name] — [call](https://www.fool.com/y)
- CScale raised $145M (secondary source, not confirmed) — https://tech-insider.org/z
"""

NOTE_B = """# Agentic networking

Summary: MCP went stateless on 2026-07-28.

- Streamable HTTP requires Mcp-Method and Mcp-Name headers. — [MCP blog](https://blog.modelcontextprotocol.io/p)
"""

PACK_FROM_MODEL = {
    "facts": [
        {"id": "x", "claim": "Back-end AI switch sales passed front-end for the first time",
         "value": "Q2 2026", "source_url": "https://www.delloro.com/news/x",
         "source_title": "Dell'Oro", "quote": "AI back-end switch sales surpassed front-end sales",
         "as_of": "2026-09-03", "kind": "statistic"},
        {"id": "y", "claim": "MCP Streamable HTTP requires routing headers",
         "value": "Mcp-Method and Mcp-Name", "source_url": "https://blog.modelcontextprotocol.io/p",
         "source_title": "MCP blog", "quote": "requires Mcp-Method and Mcp-Name headers",
         "as_of": "2026-07-28", "kind": "spec"},
        {"id": "z", "claim": "no url, must be dropped", "value": "42", "source_url": "",
         "quote": "", "as_of": "undated", "kind": "statistic"},
    ],
    "primary_sources": ["https://www.delloro.com/news/x", "https://blog.modelcontextprotocol.io/p"],
    "gaps": ["Arista 1.6T platform named 7060XE7 - flagged in the notes; confirm at "
             "https://www.fool.com/y before use"],
}

WEB_PACK = {
    "facts": [
        # same value and URL as the notes' first fact: a duplicate, dropped on merge
        {"id": "w1", "claim": "dup of the notes fact", "value": "q2 2026",
         "source_url": "https://www.delloro.com/news/x", "quote": "", "as_of": "2026-09-03",
         "kind": "statistic"},
        {"id": "w2", "claim": "UALink 2.0 published before 1.0 silicon", "value": "7 April 2026",
         "source_url": "https://www.theregister.com/u", "quote": "", "as_of": "2026-04-07",
         "kind": "date"},
    ],
    "primary_sources": ["https://www.theregister.com/u"],
    "gaps": ["Nvidia Q2 FY27 networking revenue not retrieved"],
    "method": "claude-web-tools",
}

RESEARCH_BASE = {
    "semantic_analysis": {"common_subtopics": ["scale-up", "scale-out"],
                          "related_questions": ["Is InfiniBand dead?"]},
}

failures = 0


def check(name, cond, detail=""):
    global failures
    if cond:
        print(f"  ok   {name}")
    else:
        failures += 1
        print(f"  FAIL {name} {detail}")


def notes_dir():
    d = Path(tempfile.mkdtemp(prefix="notes_"))
    (d / "a.md").write_text(NOTE_A, encoding="utf-8")
    (d / "b.md").write_text(NOTE_B, encoding="utf-8")
    (d / "ignored.txt").write_text("not markdown", encoding="utf-8")
    return d


# 1. Loading: a folder, headers per file, the digest, the flag count
print("load_research_notes")
d = notes_dir()
notes = sw.load_research_notes([str(d)])
check("two .md files, the .txt ignored", len(notes["files"]) == 2, notes["files"])
check("each file headed with its name", "===== NOTES FILE: a.md =====" in notes["text"]
      and "===== NOTES FILE: b.md =====" in notes["text"])
check("digest has one line per file", notes["digest"].count("\n- ") == 1
      and notes["digest"].startswith("- a.md: "), notes["digest"][:80])
check("flagged claims counted ([VERIFY], secondary source, not confirmed)",
      notes["flagged"] == 3, notes["flagged"])
check("a missing path is skipped, not fatal",
      sw.load_research_notes([str(d / "nope.md")])["files"] == [])
single = sw.load_research_notes([str(d / "b.md")])
check("a single file works too", single["files"] == [str(d / "b.md")])

# 2. The cap
saved = sw.NOTES_MAX_CHARS
sw.NOTES_MAX_CHARS = 120
capped = sw.load_research_notes([str(d)])
check("cap truncates and leaves later files out", len(capped["text"]) <= 120
      and "b.md" not in capped["text"], len(capped["text"]))
sw.NOTES_MAX_CHARS = saved

# 3. The pack from the notes, model stubbed
print("build_notes_pack")
import json
seen = {}


def stub_call(prompt, **kwargs):
    seen["prompt"] = prompt
    return json.dumps(PACK_FROM_MODEL)


real_call = sw.call_claude
sw.call_claude = stub_call
research = dict(RESEARCH_BASE, notes=notes)
pack = sw.build_notes_pack("Four planes of AI networking", "AI networking", "explain the planes", research)
check("the model saw the notes themselves", "THE NOTES" in seen["prompt"]
      and "Mcp-Method and Mcp-Name" in seen["prompt"])
check("the model saw the brief", "TOPIC: Four planes of AI networking" in seen["prompt"])
check("fact without a URL dropped, ids renumbered",
      [f["id"] for f in pack["facts"]] == ["f1", "f2"], [f["id"] for f in pack["facts"]])
check("facts carry their origin", all(f.get("origin") == "research-notes" for f in pack["facts"]))
check("method is research-notes", pack["method"] == "research-notes", pack["method"])
check("flagged claim sits in gaps, not facts", len(pack["gaps"]) == 1
      and "7060XE7" in pack["gaps"][0] and not any("7060XE7" in f["value"] for f in pack["facts"]))


def failing_call(prompt, **kwargs):
    raise sw.ClaudeError("model down")


sw.call_claude = failing_call
check("a failed call returns None and the run goes on",
      sw.build_notes_pack("t", "k", "i", research) is None)
sw.call_claude = real_call

# 4. Merge: notes first, duplicates dropped, gaps joined
print("merge_fact_packs")
merged = sw.merge_fact_packs(pack, WEB_PACK)
check("duplicate (same value and URL) dropped, new web fact kept",
      [f["claim"] for f in merged["facts"]] == [
          "Back-end AI switch sales passed front-end for the first time",
          "MCP Streamable HTTP requires routing headers",
          "UALink 2.0 published before 1.0 silicon"],
      [f["claim"] for f in merged["facts"]])
check("ids renumbered across the merge", [f["id"] for f in merged["facts"]] == ["f1", "f2", "f3"])
check("notes' facts keep their origin, web facts have none",
      merged["facts"][0].get("origin") == "research-notes" and not merged["facts"][2].get("origin"))
check("methods joined", merged["method"] == "research-notes+claude-web-tools", merged["method"])
check("gaps joined", len(merged["gaps"]) == 2, merged["gaps"])
check("primary sources joined without duplicates", len(merged["primary_sources"]) == 3)
skipped = sw.merge_fact_packs(pack, {"facts": [], "primary_sources": [], "gaps": [], "method": "skipped"})
check("merging with a skipped web pack keeps the notes' method",
      skipped["method"] == "research-notes" and len(skipped["facts"]) == 2, skipped["method"])

# 5. What the writer sees
print("fact_pack_text")
research["fact_pack"] = merged
text = sw.fact_pack_text(research)
check("digest above the pack", text.startswith("\nRESEARCH NOTES") and "- a.md: " in text)
check("notes facts tagged inline", "| from the author's notes" in text)
check("web fact not tagged", "UALink 2.0 published before 1.0 silicon | value: 7 April 2026 | as of 2026-04-07 | https://www.theregister.com/u\n" in text)
check("flagged claim shows as a gap", "7060XE7" in text.split("KNOWN GAPS")[1])
empty = sw.fact_pack_text({"notes": notes, "fact_pack": {"facts": []}})
check("no facts: digest still shown above the no-figures rule",
      empty.startswith("\nRESEARCH NOTES") and "state no price" in empty)
check("no notes: nothing added", not sw.fact_pack_text({"fact_pack": merged}).startswith("\nRESEARCH"))

# 6. The CLI flag exists and is passed through (parser built from main's source)
print("cli")
import inspect
src = inspect.getsource(sw.main)
check("--notes is a CLI flag", '"--notes"' in src and 'nargs="+"' in src)
check("run() receives it", "notes=args.notes" in src)
check("run() accepts it", "notes" in inspect.signature(sw.run).parameters)

# 7. app.py path resolution, when Flask is installed
try:
    import app as web
except Exception as e:  # noqa: BLE001
    print(f"  skip app._notes_paths ({type(e).__name__}: Flask or another import missing)")
else:
    rdir = web.RESEARCH_DIR
    probe = rdir / "_test_probe.md"
    rdir.mkdir(exist_ok=True)
    probe.write_text("probe", encoding="utf-8")
    try:
        got = web._notes_paths(["_test_probe.md", "../app.py", "missing.md", "../../etc/passwd"])
        check("only names inside research/ or output/ resolve",
              got == [str(probe.resolve())], got)
        check("a bare string works too", web._notes_paths("_test_probe.md") == [str(probe.resolve())])
    finally:
        try:
            probe.unlink()
        except OSError:
            print(f"  (could not remove {probe}; delete it by hand)")

print()
if failures:
    print(f"{failures} check(s) failed")
    sys.exit(1)
print("all checks passed")
