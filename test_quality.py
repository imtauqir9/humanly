"""Tests for the quality pass: fact pack plumbing, the author's take, date
context, and the post-processing bugs seen in the shipped NVIDIA article."""
import json
import os
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402


# --- em dashes -------------------------------------------------------------

def test_em_dash_between_two_clauses_becomes_semicolon_not_comma_splice():
    line = "That said, they are course-bound credentials — they validate what you learned in a guided environment."
    out = sw._strip_em_dashes(line)
    assert "credentials; they validate" in out, out
    assert "credentials, they validate" not in out


def test_em_dash_before_a_fragment_becomes_comma():
    line = "It spans two frameworks — the DLI and the NCP program."
    assert sw._strip_em_dashes(line) == "It spans two frameworks, the DLI and the NCP program."


def test_em_dash_before_conjunction_becomes_comma():
    line = "The exam is proctored — and it is not cheap."
    assert sw._strip_em_dashes(line) == "The exam is proctored, and it is not cheap."


def test_multiple_dashes_on_one_line():
    line = "First point — it matters — and a second — which is smaller."
    out = sw._strip_em_dashes(line)
    assert "—" not in out
    assert "point; it matters" in out
    assert ", and a second, which is smaller" in out


def test_pronoun_i_keeps_its_capital_after_semicolon():
    line = "Skip the Associate exam if you have a year on clusters — I did, and the badge bought me nothing."
    out = sw._strip_em_dashes(line)
    assert "clusters; I did," in out, out
    assert "; i did" not in out


def test_publisher_name_strips_www_as_a_prefix_not_as_characters():
    assert sw.publisher_name("https://www.whizlabs.com/blog/x") == "Whizlabs"
    assert sw.publisher_name("https://wwwtest.com/") == "Wwwtest"


def test_heading_dash_rule_unchanged():
    assert sw._strip_em_dashes("## DLI vs. NCP — what differs") == "## DLI vs. NCP: what differs"


# --- sources ---------------------------------------------------------------

ARTICLE = """
Demand is high (Source: https://www.idc.com). Fees are set by Pearson (Source: https://home.pearsonvue.com/nvidia).
Read the [certification page](https://www.nvidia.com/en-us/training/certification/) for details.
![NVIDIA badge](https://images.credly.com/images/abc/image.png)
*Source: Credly*
Another cite (Source: https://www.nvidia.com/en-us/training/certification/): see above.
![chart](https://www.techspot.com/articles-info/2968/bench/2025-03-18-image.png)
"""


def test_sources_are_deduped_and_stripped_of_trailing_punctuation():
    urls = sw.extract_sources(ARTICLE)
    assert urls == [
        "https://www.idc.com",
        "https://home.pearsonvue.com/nvidia",
        "https://www.nvidia.com/en-us/training/certification/",
    ], urls


def test_image_urls_are_not_listed_as_sources():
    urls = sw.extract_sources(ARTICLE)
    assert not any(u.endswith(".png") for u in urls)
    assert not any("credly" in u for u in urls)


# --- orphan image markers --------------------------------------------------

def test_orphan_image_marker_without_query_is_removed():
    body = "Intro.\n\n[IMAGE: Difficulty progression chart for NVIDIA DLI tracks]\n\n### Next\nText."
    out = sw.strip_orphan_image_markers(body)
    assert "[IMAGE:" not in out
    assert "### Next\nText." in out


def test_resolved_images_are_untouched():
    body = "![alt](https://x/y.png)\n*Source: X*\n"
    assert sw.strip_orphan_image_markers(body) == body


# --- fact pack -------------------------------------------------------------

def test_clean_fact_pack_drops_bad_rows_and_renumbers():
    raw = {"facts": [
        {"id": "z", "claim": "fee", "value": "$250", "source_url": "https://a.com/p", "quote": "Fee: $250"},
        {"id": "z", "claim": "dup", "value": "$250", "source_url": "https://a.com/p"},
        {"claim": "no url", "value": "$1", "source_url": "n/a"},
        "garbage",
    ], "primary_sources": ["https://a.com/p", "junk"], "gaps": ["validity period"]}
    pack = sw._clean_fact_pack(raw)
    assert [f["id"] for f in pack["facts"]] == ["f1"]
    assert pack["primary_sources"] == ["https://a.com/p"]
    assert pack["gaps"] == ["validity period"]


def test_fact_pack_text_forbids_specifics_when_empty():
    txt = sw.fact_pack_text({"fact_pack": {"facts": []}})
    assert "No verified facts" in txt
    assert "Do not fill the gap from memory" in txt


def test_fact_pack_text_lists_facts_with_urls_and_rules():
    research = {"fact_pack": {"facts": [
        {"id": "f1", "claim": "NCP-AII exam fee", "value": "$250",
         "source_url": "https://nvidia.com/x", "quote": "The exam costs $250.", "as_of": "2026-05"},
    ], "gaps": ["retake wait"]}}
    txt = sw.fact_pack_text(research)
    assert "[f1]" in txt and "$250" in txt and "https://nvidia.com/x" in txt
    assert "retake wait" in txt
    assert "Never widen a value into a range" in txt


# --- author's take and dates -----------------------------------------------

def test_take_block_numbers_items_and_demands_first_person():
    txt = sw.take_block("- I took the CUDA workshop\n* Networking track is underrated\n")
    assert "1. I took the CUDA workshop" in txt
    assert "2. Networking track is underrated" in txt
    assert "first person" in txt


def test_take_block_empty_when_no_take():
    assert sw.take_block("") == ""
    assert sw.take_block("   \n") == ""


def test_read_take_accepts_inline_or_file(tmp_path: Path):
    assert sw.read_take("inline text") == "inline text"
    p = tmp_path / "take.txt"
    p.write_text("from file")
    assert sw.read_take(str(p)) == "from file"
    assert sw.read_take(None) == ""


def test_date_context_names_the_current_year():
    txt = sw.date_context()
    assert str(sw.CURRENT_YEAR) in txt
    assert str(sw.CURRENT_YEAR - 1) in txt


def test_prompts_carry_facts_take_and_date(monkeypatch):
    """The writer, outliner and auditor must all see the pack, the take and the date."""
    seen = {}

    def fake_claude(prompt, system="", **kw):
        seen.setdefault("prompts", []).append(prompt + "\n" + system)
        return "# Title\n\nBody."

    monkeypatch.setattr(sw, "call_claude", fake_claude)
    monkeypatch.setattr(sw, "call_agent",
                        lambda role, prompt, system="", **kw: (seen["prompts"].append(prompt),
                                                              '{"verdict":"pass","scores":{},"issues":[]}')[1])
    research = {
        "keywords": {"primary_keyword": "nvidia certification"},
        "semantic_analysis": {},
        "take": "I sat the Associate exam in May; the DGX questions were the hard part.",
        "style_samples": "--- Sample: one ---\nShort sentences. Opinions.",
        "fact_pack": {"facts": [{"id": "f1", "claim": "fee", "value": "$250",
                                 "source_url": "https://nvidia.com/x", "quote": "q"}], "gaps": []},
    }
    sw.generate_outline("T", "kw", research, "- t1")
    sw.write_content("T", "kw", "outline", research, "- t1")
    sw.verify_content("body", "outline", "- t1", research, agents={
        "auditor": {"provider": "anthropic", "model": "m", "effort": "low"}})
    joined = "\n".join(seen["prompts"])
    assert joined.count("[f1]") >= 3, "fact pack missing from a prompt"
    assert joined.count("I sat the Associate exam") >= 3, "take missing from a prompt"
    assert joined.count("Today's date is") >= 3, "date context missing from a prompt"
    assert "Short sentences. Opinions." in joined, "style samples missing from writer"


def test_style_samples_load_from_md(tmp_path: Path, monkeypatch):
    d = tmp_path / "samples"
    d.mkdir()
    (d / "one.md").write_text("word " * 400)
    (d / "tiny.md").write_text("too short")
    monkeypatch.setattr(sw, "SAMPLE_DIR", d)
    out = sw.load_style_samples(limit_words=50)
    assert "--- Sample: one ---" in out
    assert "tiny" not in out
    assert len(out.split()) < 70
