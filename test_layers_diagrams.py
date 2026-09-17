"""Tests for the layered-teaching pass: the voice profile, the Level 1
readability check, and the diagrams the pipeline draws itself."""
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402


# --- voice -----------------------------------------------------------------

def test_voice_profile_is_built_once_then_cached(tmp_path: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(sw, "VOICE_PROFILE_PATH", tmp_path / "vp.json")
    monkeypatch.setattr(sw, "call_claude",
                        lambda prompt, **kw: (calls.append(prompt), "Short sentences. " * 30)[1])
    samples = "You build it. You measure it. Then you cut what did not move the number. " * 20
    first = sw.build_voice_profile(samples)
    second = sw.build_voice_profile(samples)
    assert first == second and len(calls) == 1
    assert "MEASURED ON THE EXCERPTS" in calls[0] and "median_sentence_words" in calls[0]
    # A change to the samples invalidates the cache.
    sw.build_voice_profile(samples + " New paragraph.")
    assert len(calls) == 2


def test_voice_profile_empty_cases(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sw, "VOICE_PROFILE_PATH", tmp_path / "vp.json")
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: "too short")
    assert sw.build_voice_profile("") == ""
    assert sw.build_voice_profile("Some samples. " * 50) == ""      # rejected as junk
    assert sw.voice_block("") == ""
    assert "THE AUTHOR'S VOICE" in sw.voice_block("Terse. Direct.")


def test_style_block_carries_samples_and_profile():
    out = sw.style_block("--- Sample: x ---\ntext", "Terse. Direct.")
    assert "STYLE TO MATCH" in out and "Terse. Direct." in out
    assert sw.style_block("", "") == ""


# --- level 1 readability ---------------------------------------------------

LONG = "This sentence " + "keeps going and going " * 12 + "until it stops."
DENSE = ("# T\n\n## Introduction\n\nHello.\n\n## The simple version\n\n" + LONG +
         "\n\n[DIAGRAM: A path | Shows: the order of steps]\n\n## How it works\n\nDetail.")


def test_check_explainer_measures_the_section_with_the_marker():
    stats = sw.check_explainer(DENSE)
    assert stats["found"] and stats["heading"] == "The simple version"
    assert not stats["ok"] and stats["long_count"] == 1
    simple = DENSE.replace(LONG, "It is a box. You put things in. You take them out.")
    good = sw.check_explainer(simple)
    assert good["ok"] and good["sentences"] == 3
    assert sw.check_explainer("# T\n\n## A\n\nno marker here.")["found"] is False


def test_simplify_explainer_targets_only_that_section(monkeypatch):
    seen = {}
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: (seen.setdefault("p", prompt), "# ok")[1])
    stats = sw.check_explainer(DENSE)
    sw.simplify_explainer(DENSE, stats, {"voice_profile": "Plain and short."})
    assert '"## The simple version"' in seen["p"]
    assert "Plain and short." in seen["p"]
    assert "Rewrite ONLY that section" in seen["p"]


# --- markers survive every pass --------------------------------------------

def test_diagram_marker_is_structural_not_prose():
    marker = "[DIAGRAM: Request path | Shows: where the cache sits — before the model]"
    assert sw._strip_em_dashes(marker) == marker
    assert marker not in sw._scannable_lines("a.\n" + marker + "\nb.")
    stripped = sw.strip_orphan_image_markers("x\n" + marker + "\n[IMAGE: a | Query: b]\ny")
    assert "[DIAGRAM:" not in stripped and "[IMAGE:" not in stripped
    assert sw.explainer_section("## H\n\n" + marker)[0] == "H"


def test_faq_answers_skip_diagram_markers():
    article = ("## FAQ\n\n### Is it fast?\n\nYes.\n[DIAGRAM: x | Shows: y]\nVery.\n")
    assert sw.parse_faq(article) == [{"question": "Is it fast?", "answer": "Yes. Very."}]


# --- spec cleaning ---------------------------------------------------------

def test_clean_diagram_spec_handles_every_shape_and_junk():
    flow = sw._clean_diagram_spec({
        "type": "flow", "title": "t",
        "nodes": ["A", {"label": "B", "note": "n"}, 7, {"label": ""}],
        "edges": [{"from": 0, "to": 1}, {"from": 9, "to": 0}, "junk", {"from": 1, "to": 1}],
    })
    assert [n["label"] for n in flow["nodes"]] == ["A", "B"]
    assert flow["edges"] == [{"from": 0, "to": 1, "label": ""}]
    assert sw._clean_diagram_spec({"type": "flow", "nodes": ["only one"]}) is None
    assert sw._clean_diagram_spec({"type": "weird", "nodes": ["A", "B"]})["type"] == "flow"
    assert sw._clean_diagram_spec("garbage") is None

    cmp_ = sw._clean_diagram_spec({"type": "compare", "columns": [
        {"title": "X", "items": ["a", "b", "", "c", "d", "e", "f"]}, {"title": "Y", "items": ["c"]}, "junk"]})
    assert len(cmp_["columns"]) == 2 and len(cmp_["columns"][0]["items"]) == 5
    assert sw._clean_diagram_spec({"type": "compare", "columns": [{"title": "X", "items": ["a"]}]}) is None

    too_many = sw._clean_diagram_spec({"type": "layers", "nodes": [f"L{i}" for i in range(20)]})
    assert len(too_many["nodes"]) == sw.DIAGRAM_MAX_NODES


# --- rendering -------------------------------------------------------------

SHAPES = [
    {"type": "flow", "title": "A request's path", "caption": "Hits never reach the model.",
     "nodes": [{"label": "User asks", "note": ""}, {"label": "Embed the question", "note": "turn words into numbers"},
               {"label": "Check the cache", "note": ""}, {"label": "Call the model", "note": "only on a miss"},
               {"label": "Answer", "note": ""}, {"label": "Store it", "note": ""}],
     "edges": [{"from": 2, "to": 4, "label": "hit"}], "columns": []},
    {"type": "cycle", "title": "Observe, think, act", "caption": "",
     "nodes": [{"label": "Observe", "note": ""}, {"label": "Think", "note": ""}, {"label": "Act", "note": ""}],
     "edges": [], "columns": []},
    {"type": "layers", "title": "The stack", "caption": "Each layer only talks to its neighbours.",
     "nodes": [{"label": "Application", "note": "what the user sees"}, {"label": "Retrieval", "note": ""},
               {"label": "Vector store", "note": "where the numbers live"}], "edges": [], "columns": []},
    {"type": "compare", "title": "Naive RAG versus knowledge graph", "caption": "Pick by the questions you get.",
     "nodes": [], "edges": [],
     "columns": [{"title": "Naive RAG", "items": ["Fast to ship", "Chunks of text", "Struggles with relationships between many things"]},
                 {"title": "Knowledge graph", "items": ["Slow to model", "Entities and edges", "Answers multi-hop questions"]}]},
]


@pytest.mark.parametrize("spec", SHAPES, ids=[s["type"] for s in SHAPES])
def test_every_shape_renders_to_valid_svg_and_a_png(tmp_path: Path, spec):
    layout = sw.layout_diagram(spec)
    assert layout["w"] == 1200 and layout["h"] > 150
    svg = sw.diagram_svg(layout)
    assert "\n" not in svg                      # single line, so Markdown leaves it alone
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    texts = " ".join(t.text or "" for t in root.iter() if t.tag.endswith("text"))
    labels = [n["label"] for n in spec["nodes"]] + [c["title"] for c in spec["columns"]]
    for label in labels:
        assert label in texts, label
    assert spec["title"] in texts and sw.AUTHOR_NAME in texts
    if spec["type"] == "cycle":
        assert "polyline" in svg and "repeats" in texts
    if spec["type"] == "flow":
        assert "stroke-dasharray" in svg and "hit" in texts

    png = tmp_path / "d.png"
    assert sw.diagram_png(layout, png) is True
    from PIL import Image
    im = Image.open(png)
    assert im.size == (1800, int(layout["h"] * 1.5))
    # Something was actually drawn: not a blank white canvas.
    assert len(im.getcolors(maxcolors=100000) or []) > 20


def test_render_and_inject_diagrams_end_to_end(tmp_path: Path, monkeypatch):
    spec = {"type": "flow", "title": "Cache path", "caption": "Hits skip the model.",
            "nodes": [{"label": "Ask"}, {"label": "Check cache"}, {"label": "Answer"}]}
    prompts = []
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: (prompts.append(prompt), json.dumps(spec))[1])
    article = ("## Simple\n\nA cache remembers answers.\n\n"
               "[DIAGRAM: Cache path | Shows: the cache sits before the model]\n\nMore.\n\n## Deep\n\nx.")
    diagrams = sw.render_diagrams(article, "slug", tmp_path)
    assert len(diagrams) == 1
    assert "A cache remembers answers." in prompts[0] and "## Deep" not in prompts[0]
    assert (tmp_path / "slug_diagram_1.png").exists() and (tmp_path / "slug_diagram_1.svg").exists()
    out = sw.inject_diagrams(article, diagrams)
    assert "![Cache path](slug_diagram_1.png)" in out
    assert "*Diagram: Hits skip the model.*" in out
    assert "[DIAGRAM:" not in out


def test_unusable_spec_drops_the_marker(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: "not json at all")
    article = "## S\n\n[DIAGRAM: x | Shows: y]\n"
    assert sw.render_diagrams(article, "slug", tmp_path) == {}
    assert "[DIAGRAM:" not in sw.strip_orphan_image_markers(article)


def test_html_inlines_the_svg_and_docx_embeds_the_png(tmp_path: Path, monkeypatch):
    spec = {"type": "layers", "title": "Three tiers",
            "nodes": [{"label": "Top"}, {"label": "Middle"}, {"label": "Bottom"}]}
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: json.dumps(spec))
    article = "# Title\n\n## Simple\n\nText.\n\n[DIAGRAM: Three tiers | Shows: the order]\n\nAfter.\n"
    diagrams = sw.render_diagrams(article, "slug", tmp_path)
    branded = sw.inject_diagrams(article, diagrams)

    html_path = sw._write_html("slug", branded, tmp_path, meta={"title": "T"}, images={},
                               generated_at="", diagrams=diagrams)
    html = html_path.read_text(encoding="utf-8")
    assert '<figure class="diagram"><svg' in html
    assert "Diagram: the order" in html
    assert 'src="slug_diagram_1.png"' not in html          # inline SVG, not a file reference

    docx_path = sw._write_docx("slug", branded, tmp_path)
    from docx import Document
    doc = Document(str(docx_path))
    assert len(doc.inline_shapes) == 1
    captions = [p.text for p in doc.paragraphs if p.text.startswith("Diagram:")]
    assert captions == ["Diagram: the order"]


def test_local_diagram_never_becomes_the_og_image(tmp_path: Path):
    images = {"[DIAGRAM: a | Shows: b]": {"alt": "a", "url": "slug_diagram_1.png", "source": "generated diagram"},
              "[IMAGE: c | Query: d]": {"alt": "c", "url": "https://x.test/p.jpg", "source": "https://x.test"}}
    html = sw._write_html("slug", "# T\n\nbody", tmp_path, meta={}, images=images,
                          generated_at="2026-09-12T00:00:00Z").read_text(encoding="utf-8")
    assert 'og:image" content="https://x.test/p.jpg"' in html
    assert 'og:image" content="slug_diagram_1.png"' not in html


# --- prompts ---------------------------------------------------------------

def test_outline_writer_and_auditor_all_teach_in_layers(monkeypatch):
    seen = []
    monkeypatch.setattr(sw, "call_claude", lambda prompt, system="", **kw: (seen.append(prompt + "\n" + system), "# T\n\nBody.")[1])
    monkeypatch.setattr(sw, "call_agent",
                        lambda role, prompt, system="", **kw: (seen.append(prompt),
                                                              '{"verdict":"pass","scores":{},"issues":[]}')[1])
    research = {"keywords": {"primary_keyword": "k"}, "semantic_analysis": {}, "take": "",
                "style_samples": "", "voice_profile": "Short sentences. No throat-clearing.",
                "fact_pack": {"facts": [], "gaps": []}}
    sw.generate_outline("T", "k", research, "- t1")
    sw.write_content("T", "k", "outline", research, "- t1")
    sw.verify_content("body", "outline", "- t1", research,
                      agents={"auditor": {"provider": "anthropic", "model": "m", "effort": "low"}})
    sw.humanize_content("body", research)
    sw.apply_fixes("body", [{"id": "i1", "quote": "q", "problem": "p", "fix": "f"}], research)
    joined = "\n".join(seen)
    assert joined.count("LEVEL 1 - The simple version") >= 3, "levels missing from a prompt"
    assert joined.count("[DIAGRAM:") >= 3
    assert joined.count("No throat-clearing.") >= 5, "voice profile missing from a prompt"
    assert "10. LAYERING" in joined
