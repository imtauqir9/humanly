"""Step 1.55 harness: deep research with the planning and web calls stubbed, so
the question planning, the per-question research, the merge order, the raised
cap and the failure paths can be checked without an API call.

Run:  python test_deep.py
"""

import inspect
import os
import sys
import threading

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

import seo_writer as sw

failures = 0


def check(name, cond, detail=""):
    global failures
    if cond:
        print(f"  ok   {name}")
    else:
        failures += 1
        print(f"  FAIL {name} {detail}")


def fact(value, url, claim="c"):
    return {"claim": claim, "value": value, "source_url": url, "source_title": "t",
            "quote": "q", "as_of": "2026-10", "kind": "statistic"}


BASE_PACK = sw._clean_fact_pack({
    "facts": [fact("400G", "https://vendor.example/a", "existing fact")],
    "primary_sources": ["https://vendor.example/a"],
    "gaps": ["Price of the 1.6T optic not found"],
    "method": "claude-web-tools",
})
RESEARCH = {"semantic_analysis": {"common_subtopics": ["optics"], "related_questions": ["Is it dead?"]},
            "fact_pack": BASE_PACK}

PLAN = {"questions": [
    {"question": "What do operators report about failure rates?", "angle": "practitioner", "why": "w"},
    {"question": "What does a 1.6T optic cost?", "angle": "buyer", "why": "w"},
    {"question": "what do operators report about failure rates?", "angle": "skeptic", "why": "dup"},
    {"question": "", "angle": "data"},
    "not a dict",
    {"question": "Which standard defines it?", "angle": "standards", "why": "w"},
]}
seen = {"plan_prompt": "", "web": [], "threads": set()}


def stub_claude(prompt, **kwargs):
    seen["plan_prompt"] = prompt
    import json
    return json.dumps(PLAN)


def stub_web(prompt, **kwargs):
    seen["web"].append((prompt, kwargs))
    seen["threads"].add(threading.get_ident())
    if "failure rates" in prompt:
        return {"facts": [fact("400G", "https://vendor.example/a"),          # duplicate of the pack
                          fact("2.1%", "https://ops.example/f", "failure rate")],
                "primary_sources": ["https://ops.example/f"], "gaps": []}
    if "cost" in prompt:
        return {"facts": [fact(f"${i}", f"https://price.example/{i}") for i in range(12)],
                "primary_sources": ["https://price.example/0"], "gaps": ["No list price for 2027"]}
    raise sw.ClaudeError("web tools down")


real_claude, real_web = sw.call_claude, sw._claude_web_call
sw.call_claude, sw._claude_web_call = stub_claude, stub_web
try:
    # 1. Planning
    print("plan_deep_research")
    qs = sw.plan_deep_research("Optics", "1.6T optics", "for architects", RESEARCH)
    check("duplicates, blanks and non-dicts dropped", [q["angle"] for q in qs] ==
          ["practitioner", "buyer", "standards"], qs)
    check("planner told what is already established", "existing fact" in seen["plan_prompt"])
    check("planner shown the gaps", "Price of the 1.6T optic not found" in seen["plan_prompt"])

    # 2. The whole step
    print("deep_research")
    out = sw.deep_research("Optics", "1.6T optics", "for architects", RESEARCH)
    check("one web call per question", len(seen["web"]) == 3, len(seen["web"]))
    check("each call has its own label and the per-question budget",
          sorted(k["label"] for _, k in seen["web"]) == ["deep-1", "deep-2", "deep-3"]
          and all(k["searches"] == sw.DEEP_SEARCHES and k["fetches"] == sw.DEEP_FETCHES
                  for _, k in seen["web"]))
    check("the existing pack's fact stays first", out["facts"][0]["claim"] == "existing fact")
    check("a duplicate of a pack fact is dropped",
          sum(1 for f in out["facts"] if f["value"] == "400G") == 1)
    check("new facts tagged with their origin and question",
          all(f.get("origin") == "deep-research" and f.get("question") for f in out["facts"][1:]))
    check("each question capped at its share",
          sum(1 for f in out["facts"] if "price.example" in f["source_url"]) == sw.DEEP_FACTS_PER_QUESTION)
    check("ids renumbered", [f["id"] for f in out["facts"]] == [f"f{i}" for i in range(1, len(out["facts"]) + 1)])
    check("cap raised and recorded", out.get("max_facts") == sw.DEEP_MAX_FACTS)
    check("a failed question becomes a gap, the run goes on",
          any("Which standard defines it?" in g for g in out["gaps"]))
    check("the question's own gaps joined", "No list price for 2027" in out["gaps"])
    check("questions saved with their counts and errors",
          [q["facts"] for q in out["deep_questions"]] == [2, 8, 0]
          and "error" in out["deep_questions"][2] and "error" not in out["deep_questions"][0])
    check("method records the step", out["method"] == "claude-web-tools+deep-research", out["method"])
    check("sources joined", "https://ops.example/f" in out["primary_sources"])
    text = sw.fact_pack_text({"fact_pack": out})
    check("writer sees deep facts tagged", "| from deep research" in text)

    # 3. The raised cap survives later steps
    print("cap carried through")
    big = sw._clean_fact_pack({"facts": [fact(str(i), f"https://x.example/{i}") for i in range(40)],
                               "max_facts": sw.DEEP_MAX_FACTS, "deep_questions": [{"question": "q"}]})
    check("40 facts kept under the deep cap", len(big["facts"]) == 40)
    check("default cap still applies without it",
          len(sw._clean_fact_pack({"facts": big["facts"]})["facts"]) == sw.FACT_PACK_MAX_FACTS)
    merged = sw.merge_fact_packs({"facts": [], "method": "research-notes"}, big)
    check("merge keeps the cap and the questions",
          len(merged["facts"]) == 40 and merged.get("deep_questions") == [{"question": "q"}])
    sw._claude_web_call = lambda prompt, **kw: {"resolutions": []}
    resolved = sw.resolve_fact_gaps("t", "k", "i", {"fact_pack": dict(big, gaps=["one gap"])})
    check("gap resolver keeps the cap and the questions",
          len(resolved["facts"]) == 40 and resolved.get("deep_questions") == [{"question": "q"}])

    # 4. Planning failure leaves the pack alone
    print("failures")

    def broken(prompt, **kwargs):
        raise sw.ClaudeError("down")

    sw.call_claude = broken
    check("failed planning returns the pack untouched",
          sw.deep_research("t", "k", "i", RESEARCH) is BASE_PACK)
    sw.call_claude = lambda prompt, **kw: '{"questions": []}'
    check("no questions: pack untouched", sw.deep_research("t", "k", "i", RESEARCH) is BASE_PACK)
finally:
    sw.call_claude, sw._claude_web_call = real_claude, real_web

# 5. Wiring
print("cli and app")
src = inspect.getsource(sw.main)
check("--deep is a CLI flag passed through",
      '"--deep"' in src and "deep=args.deep" in src and "deep" in inspect.signature(sw.run).parameters)
run_src = inspect.getsource(sw.run)
check("deep research runs before the gap resolver",
      0 < run_src.index("deep_research(") < run_src.index("resolve_fact_gaps("))
app_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), encoding="utf-8").read()
check("the run API passes deep through", 'data.get("deep")' in app_src and '"--deep"' in app_src)

print()
if failures:
    print(f"{failures} check(s) failed")
    sys.exit(1)
print("all checks passed")
