"""The Write page stays small; the Library page shows everything."""
import json
import os
from pathlib import Path

os.environ["APP_PASSWORD"] = ""
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import app as a  # noqa: E402


def _article(out: Path, slug: str, title: str, extras=()):
    (out / f"{slug}_meta.json").write_text(json.dumps({
        "generated_at": "2026-09-13T10:00:00Z", "seo_meta": {"title": title, "description": f"About {title}"},
        "images": [{"url": "x"}]}), encoding="utf-8")
    (out / f"{slug}.md").write_text("word " * 50, encoding="utf-8")
    for suffix in extras:
        (out / f"{slug}{suffix}").write_text("x", encoding="utf-8")


def test_home_shows_five_recent_and_links_to_the_library(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    for i in range(7):
        _article(tmp_path, f"art-{i}", f"Article {i}")
    html = a.app.test_client().get("/").get_data(as_text=True)
    recent = html[html.index('id="articlesGrid"'):html.index('id="libraryLink"')]   # the JS template has one too
    assert recent.count('<article class="item">') == 5
    assert "Open the library (7 articles)" in html
    assert '<a href="/library">Library</a>' in html and '<a href="/" class="active">Write</a>' in html
    assert 'id="radarPanel"' in html and 'id="radarBtn"' in html


def test_library_lists_everything_with_every_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    _article(tmp_path, "full", "Full article",
             extras=("_diagram_1.png", "_facts.json", "_linkedin.md", "_video.md", "_voiceover.mp3", "_review.json"))
    for i in range(6):
        _article(tmp_path, f"art-{i}", f"Article {i}")
    html = a.app.test_client().get("/library").get_data(as_text=True)
    assert html.count('class="article-card"') == 7 and "7 articles" in html
    for label in ("Diagram", "Facts", "LinkedIn", "Video script", "Visual track", "Voiceover (mp3)", "Review"):
        assert label in html, label
    assert 'href="/output/full_diagram_1.png"' in html and 'href="/output/full_facts.json"' in html
    assert 'class="active">Library</a>' in html
    assert "No radar run yet" in html


def test_library_lists_radar_runs_and_their_briefs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    radar = {"themes": [{"title": "Agents colluding"}, {"title": "Coding agents fail"}]}
    for name in ("radar_2026-09-13.json", "radar_latest.json", "radar_2026-09-06.json"):
        (tmp_path / name).write_text(json.dumps(radar), encoding="utf-8")
    (tmp_path / "radar_2026-09-13.md").write_text("# r", encoding="utf-8")
    (tmp_path / "radar_2026-09-13_brief_2.md").write_text("# b", encoding="utf-8")
    (tmp_path / "radar_2026-09-13_brief_x.md").write_text("junk", encoding="utf-8")
    runs = a.list_radars()
    assert [r["date"] for r in runs] == ["2026-09-13", "2026-09-06"]      # latest.json is not a run
    assert runs[0]["theme_count"] == 2 and runs[0]["top_theme"] == "Agents colluding"
    assert runs[0]["briefs"] == [{"index": 2, "file": "radar_2026-09-13_brief_2.md", "title": "Coding agents fail"}]
    assert runs[1]["briefs"] == []
    html = a.app.test_client().get("/library").get_data(as_text=True)
    assert "2. Coding agents fail" in html and 'href="/output/radar_2026-09-13.md"' in html


def test_usage_page_carries_the_nav(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    html = a.app.test_client().get("/usage").get_data(as_text=True)
    assert 'href="/library"' in html and 'href="/"' in html


def _evaluation(out: Path, slug: str, revised: str | None = None, title: str | None = None):
    record = {"outcome": "passed", "finished_at": "2026-10-10T23:38:00+00:00",
              "rounds": [{"issues": [{"id": "i1"}, {"id": "i2"}], "applied": ["i1"]}]}
    if title:
        record["title"] = title
    (out / f"{slug}_review.json").write_text(json.dumps(record), encoding="utf-8")
    if revised is not None:
        (out / f"{slug}_revised.md").write_text(revised, encoding="utf-8")


def test_library_lists_draft_evaluations_with_the_corrected_version(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    uuid_slug = "838f0d44ae7e4e1b9651e0dfee518893"
    _evaluation(tmp_path, uuid_slug, revised="# Why Agents Need Harnesses\n\nbody")
    _evaluation(tmp_path, "unrevised-draft", title="An Unrevised Draft")
    _article(tmp_path, "my-article", "My Article")
    _evaluation(tmp_path, "my-article")            # an article's audit stays on its card
    html = a.app.test_client().get("/library").get_data(as_text=True)
    section = html[html.index('id="evaluations"'):html.index("Radar runs")]
    assert "Why Agents Need Harnesses" in section     # named from the corrected version's heading
    assert f'href="/output/{uuid_slug}_revised.md" download>Corrected version' in section
    assert "An Unrevised Draft" in section and "unrevised-draft_revised.md" not in section
    assert "1 of 2" in section
    assert "my-article" not in section


def test_review_page_offers_the_corrected_version_only_when_there_is_one(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    _evaluation(tmp_path, "fixed", revised="# Fixed\n")
    _evaluation(tmp_path, "untouched")
    client = a.app.test_client()
    assert 'href="/output/fixed_revised.md" download>Download corrected version' in \
        client.get("/review/fixed").get_data(as_text=True)
    assert "Download corrected version" not in client.get("/review/untouched").get_data(as_text=True)


def test_pasted_drafts_are_named_from_their_text_not_a_uuid():
    assert a._pasted_draft_name("Intro line\n\n## Real Title\nbody") == "Real Title"
    assert a._pasted_draft_name("one two three four five six seven eight nine") == \
        "one two three four five six seven eight"
    # Passed on the command line, so it must never read as a flag.
    assert a._pasted_draft_name("- bullet first\nmore") == "bullet first"
    assert a._pasted_draft_name("# --apply everything") == "apply everything"
