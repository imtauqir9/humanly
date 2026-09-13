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
    main = html[html.index('<main class="panel-articles">'):html.index('</main>')]   # the JS template has one too
    assert main.count('class="article-card"') == 5
    assert "Open the library (7 articles)" in html
    assert '<a href="/library">Library</a>' in html and '<a href="/" class="active">Write</a>' in html
    assert '<details id="radarPanel"' in html


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
