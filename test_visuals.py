"""Tests for the visual-learning layer: the new diagram shapes and styles,
highlights and callouts, the visual plan, the look-and-revise critique, the
signature card, the learning aids and the interactive HTML."""
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402


NEW_SHAPES = [
    {"type": "timeline", "title": "The path", "nodes": [
        {"label": "Free course", "note": "Week 1"}, {"label": "Associate exam", "note": "Month 2"},
        {"label": "Professional exam", "note": "Month 6"}]},
    {"type": "tree", "title": "Which track?", "nodes": ["Write CUDA?", "Accelerated", "Generative AI"],
     "edges": [{"from": 0, "to": 1, "label": "yes"}, {"from": 0, "to": 2, "label": "no"}]},
    {"type": "graph", "title": "RAG request", "nodes": ["Question", "Embedder", "Store", "LLM", "Cache"],
     "edges": [{"from": 0, "to": 1}, {"from": 1, "to": 2}, {"from": 2, "to": 3},
               {"from": 0, "to": 4}, {"from": 4, "to": 3, "label": "hit"}]},
    {"type": "hub", "title": "The role", "nodes": ["Architect", "Data", "Models", "Security", "Evals"]},
    {"type": "funnel", "title": "Applicants to hires", "nodes": ["Apply", "Screen", "Interview", "Hire"]},
    {"type": "before_after", "title": "Then and now", "columns": [
        {"title": "Before", "items": ["Guess", "Pay"]}, {"title": "After", "items": ["Know", "Free"]}]},
    {"type": "quadrant", "title": "Cost against difficulty", "axes": {"x": "Cost", "y": "Difficulty"},
     "nodes": [{"label": "NCA", "x": 0.2, "y": 0.2}, {"label": "NCP", "x": 0.8, "y": 0.9},
               {"label": "AWS", "x": 0.6, "y": 0.5}]},
    {"type": "spectrum", "title": "Code expected", "axes": {"low": "None", "high": "Daily CUDA"},
     "nodes": [{"label": "Infra", "x": 0.2}, {"label": "CUDA", "x": 0.9}]},
    {"type": "bar", "title": "Exam fees", "unit": "$",
     "data": [{"label": "Associate", "value": 125}, {"label": "Professional", "value": 400}]},
    {"type": "line", "title": "Takers", "data": [{"label": "2023", "value": 10},
                                                 {"label": "2024", "value": 30},
                                                 {"label": "2025", "value": 70}]},
    {"type": "card", "title": "The mental model", "nodes": [
        {"label": "Start small", "note": "the Associate exam"}, {"label": "Pick by work"},
        {"label": "Practice first"}]},
]


def _labels(spec):
    return ([n["label"] for n in spec["nodes"]] + [c["title"] for c in spec["columns"]]
            + [d["label"] for d in spec["data"]])


@pytest.mark.parametrize("style", sw.DIAGRAM_STYLES)
@pytest.mark.parametrize("raw", NEW_SHAPES, ids=[s["type"] for s in NEW_SHAPES])
def test_every_new_shape_renders_in_every_style(tmp_path: Path, raw, style):
    spec = sw._clean_diagram_spec(raw)
    assert spec and spec["type"] == raw["type"]
    layout = sw.layout_diagram(spec, style)
    assert layout["style"] == style and layout["h"] > 150
    svg = sw.diagram_svg(layout)
    assert "\n" not in svg
    root = ET.fromstring(svg)
    texts = " ".join(t.text or "" for t in root.iter() if t.tag.endswith("text"))
    for label in _labels(spec):
        assert label in texts, label
    assert spec["title"] in texts
    png = tmp_path / "d.png"
    assert sw.diagram_png(layout, png, scale=1.0) is True
    from PIL import Image
    assert len(Image.open(png).getcolors(maxcolors=100000) or []) > 20
    # The style's active colours never leak out of the layout call.
    assert sw._DG_COLORS["border"] == sw._DG_STYLE_SETS["clean"]["border"]


def test_parts_carry_data_node_for_the_web_page():
    spec = sw._clean_diagram_spec(NEW_SHAPES[0])
    svg = sw.diagram_svg(sw.layout_diagram(spec))
    for i in range(3):
        assert f'data-node="{i}"' in svg
    bars = sw.diagram_svg(sw.layout_diagram(sw._clean_diagram_spec(NEW_SHAPES[8])))
    assert 'data-value="125"' in bars and 'data-value="400"' in bars


def test_arrowheads_match_their_line_colour():
    spec = sw._clean_diagram_spec({"type": "before_after", "title": "t", "columns": [
        {"title": "A", "items": ["x"]}, {"title": "B", "items": ["y"]}]})
    svg = sw.diagram_svg(sw.layout_diagram(spec))
    hot = sw._DG_STYLE_SETS["clean"]["hot"].lstrip("#")
    assert f'id="dgA{hot}"' in svg and f"url(#dgA{hot})" in svg


def test_chart_values_must_come_from_the_section():
    section = "The Associate exam costs $125 and the Professional costs $400."
    raw = {"type": "bar", "title": "Fees", "unit": "$", "data": [
        {"label": "Associate", "value": 125}, {"label": "Professional", "value": "$400"},
        {"label": "Invented", "value": 999}]}
    spec = sw._clean_diagram_spec(raw, section)
    assert [d["label"] for d in spec["data"]] == ["Associate", "Professional"]
    only_one = {**raw, "data": [{"label": "Associate", "value": 125}, {"label": "X", "value": 7}]}
    assert sw._clean_diagram_spec(only_one, section) is None


def test_shapes_that_teach_nothing_are_refused():
    assert sw._clean_diagram_spec({"type": "hub", "nodes": ["Centre", "A", "B"]}) is None
    assert sw._clean_diagram_spec({"type": "tree", "nodes": ["A", "B", "C"]}) is None   # no edges
    assert sw._clean_diagram_spec({"type": "before_after", "columns": [
        {"title": "A", "items": ["x"]}]}) is None


def test_highlight_and_callouts_are_kept_only_when_they_point_somewhere():
    spec = sw._clean_diagram_spec({"type": "flow", "nodes": ["A", "B", "C"], "highlight": 1,
                                   "callouts": [{"target": 2, "text": "look here"},
                                                {"target": 9, "text": "nowhere"},
                                                {"target": 0, "text": ""}, "junk"]})
    assert spec["highlight"] == 1
    assert spec["callouts"] == [{"target": 2, "text": "look here"}]
    assert sw._clean_diagram_spec({"type": "flow", "nodes": ["A", "B", "C"],
                                   "highlight": 7})["highlight"] == -1
    svg = sw.diagram_svg(sw.layout_diagram(spec))
    assert "look here" in svg and 'stroke-width="3.5"' in svg     # legend and highlight ring


def test_marker_flags_are_parsed_off_the_shows_text():
    m = sw.DIAGRAM_MARKER_RE.search("[DIAGRAM: Map | Shows: every track at once | Signature | Explore]")
    assert sw._marker_parts(m) == ("Map", "every track at once", {"signature", "explore"})
    m = sw.DIAGRAM_MARKER_RE.search("[DIAGRAM: Map | Shows: a | b]")
    assert sw._marker_parts(m) == ("Map", "a | b", set())


# --- the visual plan ---------------------------------------------------------

ARTICLE = """# NVIDIA certification

## Introduction

Intro text.

## The simple version

There are two tiers.

[DIAGRAM: Tier ladder | Shows: two tiers]

## Choosing a track

Pick the track that matches what you do every day at work.

Then book the exam.

[DIAGRAM: Exam booking | Shows: you book online]

## Costs

The Associate costs $125 and the Professional costs $400.

## FAQ

### Is it hard?

Yes.
"""


def test_plan_visuals_keeps_drops_adds_and_picks_a_signature(monkeypatch):
    plan = {"hard_ideas": ["Which track fits"], "keep": [1], "signature": 0, "explore": 0,
            "add": [{"section": "Choosing a track", "after": "matches what you do every day",
                     "title": "Which track fits", "shows": "pick by daily work", "signature": True},
                    {"section": "Costs", "after": "", "title": "Fees", "shows": "Associate is cheapest",
                     "explore": True},
                    {"section": "FAQ", "title": "Nope", "shows": "never in an FAQ"}]}
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: json.dumps(plan))
    out = sw.plan_visuals(ARTICLE, "NVIDIA certification")
    assert "[DIAGRAM: Tier ladder | Shows: two tiers]" in out
    assert "Exam booking" not in out                                   # dropped
    sig = "[DIAGRAM: Which track fits | Shows: pick by daily work | Signature]"
    assert sig in out
    # Lands after the paragraph it explains, before the next one.
    assert out.index("every day at work.") < out.index(sig) < out.index("Then book the exam.")
    assert "[DIAGRAM: Fees | Shows: Associate is cheapest | Explore]" in out
    assert out.index("Explore]") < out.index("## FAQ")
    assert "Nope" not in out


def test_plan_visuals_never_strips_the_simple_version(monkeypatch):
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: json.dumps({"keep": [], "add": []}))
    out = sw.plan_visuals(ARTICLE, "T")
    assert "Tier ladder" in out and "Exam booking" not in out


def test_plan_visuals_leaves_the_article_alone_on_a_bad_answer(monkeypatch):
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: "no json here")
    assert sw.plan_visuals(ARTICLE, "T") == ARTICLE
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: '{"title": "unrelated"}')
    assert sw.plan_visuals(ARTICLE, "T") == ARTICLE


# --- the critique ---------------------------------------------------------------

FLOW = {"type": "flow", "title": "Path", "caption": "c", "nodes": ["Ask", "Check", "Answer"]}


def _fake(spec_answer, review):
    calls = []

    def fake(prompt, images=None, **kw):
        calls.append({"prompt": prompt, "images": images})
        if images:
            return json.dumps(review.pop(0) if review else {"verdict": "keep"})
        return json.dumps(spec_answer)
    return fake, calls


def test_critique_looks_at_the_png_and_can_redraw(tmp_path: Path, monkeypatch):
    better = {**FLOW, "type": "layers", "nodes": ["Top", "Middle", "Bottom"]}
    fake, calls = _fake(FLOW, [{"verdict": "revise", "problems": ["order is a stack"], "spec": better}])
    monkeypatch.setattr(sw, "call_claude", fake)
    article = "## S\n\nText.\n\n[DIAGRAM: Path | Shows: the order]\n"
    out = sw.render_diagrams(article, "slug", tmp_path)
    d = next(iter(out.values()))
    assert d["type"] == "layers"
    looked = [c for c in calls if c["images"]]
    assert looked and looked[0]["images"][0][:8] == b"\x89PNG\r\n\x1a\n"
    saved = json.loads((tmp_path / "slug_diagram_1.json").read_text(encoding="utf-8"))
    assert saved["spec"]["type"] == "layers"


def test_critique_drop_removes_the_picture_and_renumbers(tmp_path: Path, monkeypatch):
    fake, _ = _fake(FLOW, [{"verdict": "drop", "problems": ["restates a sentence"]}])
    monkeypatch.setattr(sw, "call_claude", fake)
    article = ("## S\n\n[DIAGRAM: One | Shows: a]\n\n## T\n\n[DIAGRAM: Two | Shows: b]\n")
    out = sw.render_diagrams(article, "slug", tmp_path)
    assert list(out) == ["[DIAGRAM: Two | Shows: b]"]
    assert out["[DIAGRAM: Two | Shows: b]"]["png"] == "slug_diagram_1.png"
    assert not (tmp_path / "slug_diagram_2.png").exists()


def test_signature_is_never_dropped_and_gets_a_share_card(tmp_path: Path, monkeypatch):
    fake, _ = _fake(FLOW, [{"verdict": "drop"}])
    monkeypatch.setattr(sw, "call_claude", fake)
    article = "## S\n\n[DIAGRAM: Map | Shows: everything | Signature]\n"
    out = sw.render_diagrams(article, "slug", tmp_path)
    d = next(iter(out.values()))
    assert d["style"] == "bold" and "signature" in d["flags"]
    from PIL import Image
    assert Image.open(tmp_path / d["card"]).size == (1080, 1350)


def test_rerun_clears_stale_higher_numbered_files(tmp_path: Path, monkeypatch):
    (tmp_path / "slug_diagram_3.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: json.dumps(FLOW))
    sw.render_diagrams("## S\n\n[DIAGRAM: x | Shows: y]\n", "slug", tmp_path, critique=False)
    assert (tmp_path / "slug_diagram_1.svg").exists()
    assert not (tmp_path / "slug_diagram_3.svg").exists()


# --- learning aids ----------------------------------------------------------------

AIDS = {"checks": [{"section": "Choosing a track", "question": "You run clusters. Which track?",
                    "answer": "AI Infrastructure."},
                   {"section": "Introduction", "question": "skip me", "answer": "x"}],
        "mental_model": {"title": "The mental model", "points": [
            {"label": "Start small", "note": "Associate first"}, {"label": "Pick by work"},
            {"label": "Practise first"}], "caption": "Certify what you do."}}


def test_learning_aids_place_checks_and_the_card(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: json.dumps(AIDS))
    aids = sw.generate_learning_aids(ARTICLE, "T")
    page, presets = sw.apply_learning_aids(ARTICLE, aids)
    check = "> **Check yourself:** You run clusters. Which track?"
    assert check in page and "skip me" not in page
    assert page.index("Then book the exam.") < page.index(check) < page.index("## Costs")
    (marker, spec), = presets.items()
    assert "| Summary]" in marker and page.index(marker) < page.index("## FAQ")
    assert spec["type"] == "card" and len(spec["nodes"]) == 3

    # The card is drawn from the preset: no spec call, no critique.
    monkeypatch.setattr(sw, "call_claude", lambda *a, **k: pytest.fail("no Claude call expected"))
    diagrams = sw.render_diagrams(f"## Wrap-up\n\n{marker}\n", "slug", tmp_path, presets=presets)
    assert diagrams[marker]["type"] == "card"


def test_learning_aids_survive_a_bad_answer(monkeypatch):
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: "nope")
    assert sw.generate_learning_aids(ARTICLE, "T") == {}
    assert sw.apply_learning_aids(ARTICLE, {}) == (ARTICLE, {})


# --- the web page -------------------------------------------------------------------

def test_html_steps_explores_folds_and_scrollytells(tmp_path: Path, monkeypatch):
    flow = {"type": "flow", "title": "Cache path", "caption": "Hits skip the model.",
            "nodes": [{"label": "Embed question"}, {"label": "Check cache"}, {"label": "Call model"}]}
    bar = {"type": "bar", "title": "Fees", "unit": "$", "slider": {"label": "Your budget", "keep": "below"},
           "data": [{"label": "Associate", "value": 125}, {"label": "Professional", "value": 400}]}
    article = ("# T\n\n## How it works\n\n[DIAGRAM: Cache path | Shows: order]\n\n"
               "First we embed the question into numbers.\n\n"
               "Then we check the cache for a close match.\n\n"
               "On a miss we call the model and store the answer.\n\n"
               "> **Check yourself:** What happens on a hit?\n>\n> **Answer:** The model is skipped.\n\n"
               "## Costs\n\nThe Associate costs $125, the Professional $400.\n\n"
               "[DIAGRAM: Fees | Shows: Associate is cheapest | Explore]\n")
    specs = iter([flow, bar])
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: json.dumps(next(specs)))
    diagrams = sw.render_diagrams(article, "slug", tmp_path, critique=False)
    branded = sw.inject_diagrams(article, diagrams)
    html = sw._write_html("slug", branded, tmp_path, meta={"title": "T"}, images={},
                          diagrams=diagrams).read_text(encoding="utf-8")
    assert 'data-steps="' in html and 'class="dg-next"' in html
    assert 'data-explore="' in html and 'type="range"' in html and 'max="400"' in html
    assert '<details class="check"><summary><strong>Check yourself:</strong>' in html
    assert '<div class="scrolly">' in html and 'data-step="0"' in html and 'data-step="1"' in html
    assert "IntersectionObserver" in html                       # the script rides along
    assert html.count("<script>") == 1


def test_rerender_brings_back_the_interactive_diagrams(tmp_path: Path, monkeypatch):
    spec = {"type": "flow", "title": "Path", "nodes": ["Ask", "Check", "Answer"]}
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: json.dumps(spec))
    article = "# T\n\n## S\n\n[DIAGRAM: Path | Shows: order]\n"
    diagrams = sw.render_diagrams(article, "slug", tmp_path, critique=False)
    (tmp_path / "slug.md").write_text(sw.inject_diagrams(article, diagrams), encoding="utf-8")
    html = sw.rerender("slug", tmp_path).read_text(encoding="utf-8")
    assert 'data-steps="' in html
