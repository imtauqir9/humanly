"""Tests for the public article feed: /feed.json, /feed.xml, /embed.js -
no auth required even with a password set, real images only, permalinks
that resolve, and the JSON Feed / RSS shapes those endpoints promise."""
import json
import os
import re
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import app as a  # noqa: E402  (APP_PASSWORD deliberately left to whatever the suite already set; tests that care about it monkeypatch a.APP_PASSWORD directly, not the env var, since the module is cached across test files and re-reading the env would not help)


def _seed(tmp_path: Path, slug: str, *, images=None, html=True, mtime_offset=0):
    (tmp_path / f"{slug}_meta.json").write_text(json.dumps({
        "generated_at": "2026-07-23T07:16:37Z",
        "seo_meta": {"title": slug.replace("-", " ").title(), "description": f"Summary of {slug}."},
        "images": images or [],
    }), encoding="utf-8")
    (tmp_path / f"{slug}.md").write_text("word " * 200, encoding="utf-8")
    if html:
        (tmp_path / f"{slug}.html").write_text(
            f'<html><head></head><body><h1>{slug}</h1><p>Body of {slug} &amp; more.</p></body></html>',
            encoding="utf-8")
    if mtime_offset:
        import time
        t = (tmp_path / f"{slug}_meta.json").stat().st_mtime + mtime_offset
        os.utime(tmp_path / f"{slug}_meta.json", (t, t))


def test_feed_json_requires_no_auth_even_with_password_set(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "APP_PASSWORD", "secret123")
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    _seed(tmp_path, "a1")
    c = a.app.test_client()
    r = c.get("/feed.json")            # no auth header, no cookie
    assert r.status_code == 200
    r2 = c.get("/feed.xml")
    assert r2.status_code == 200
    r3 = c.get("/embed.js")
    assert r3.status_code == 200
    # a genuinely protected route still requires a password
    assert c.get("/library").status_code in (302, 401)


def test_feed_json_shape_and_ordering(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(a.sw_decisions, "SITE_URL", "")
    _seed(tmp_path, "older")
    _seed(tmp_path, "newer", mtime_offset=10)
    c = a.app.test_client()
    j = c.get("/feed.json").get_json()
    assert j["version"] == "https://jsonfeed.org/version/1.1"
    assert [it["id"] for it in j["items"]] == ["newer", "older"]      # newest first
    item = j["items"][0]
    assert item["title"] == "Newer" and item["summary"] == "Summary of newer."
    assert "content_html" in item and "<h1>newer</h1>" in item["content_html"]
    assert item["_word_count"] == 200
    assert j["authors" if "authors" in j else "author"]


def test_feed_json_content_toggle_and_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    for i in range(5):
        _seed(tmp_path, f"art-{i}", mtime_offset=i)
    c = a.app.test_client()
    j = c.get("/feed.json?limit=2").get_json()
    assert len(j["items"]) == 2
    j2 = c.get("/feed.json?content=0").get_json()
    assert all("content_html" not in it for it in j2["items"])
    assert all("content_text" in it for it in j2["items"])
    j3 = c.get("/feed.json?limit=9999").get_json()
    assert len(j3["items"]) == 5                                     # capped by what exists, not FEED_MAX_LIMIT


def test_feed_prefers_real_images_and_falls_back_to_the_diagram(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    _seed(tmp_path, "with-bad-image", images=[
        {"url": "https://media.licdn.com/dms/image/v2/x?e=1&t=tok"},   # expiring CDN, refused
        {"url": "https://cdn.test/img/real.png"},                      # durable, kept
    ])
    _seed(tmp_path, "with-no-image", images=[], mtime_offset=5)
    (tmp_path / "with-no-image_diagram_1.png").write_bytes(b"PNGDATA")
    c = a.app.test_client()
    items = {it["id"]: it for it in c.get("/feed.json").get_json()["items"]}
    assert items["with-bad-image"]["image"] == "https://cdn.test/img/real.png"
    assert "/dl/" in items["with-no-image"]["image"] and "diagram_1.png" in items["with-no-image"]["image"]


def test_feed_permalink_uses_site_url_or_a_working_signed_link(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    _seed(tmp_path, "a1")
    c = a.app.test_client()

    monkeypatch.setattr(a.sw_decisions, "SITE_URL", "")
    j = c.get("/feed.json").get_json()
    url = j["items"][0]["url"]
    assert url.startswith("http://localhost/dl/")
    resolved = c.get(url.replace("http://localhost", ""))
    assert resolved.status_code == 200 and b"<h1>a1</h1>" in resolved.data

    monkeypatch.setattr(a.sw_decisions, "SITE_URL", "https://imrantauqir.com")
    j2 = c.get("/feed.json").get_json()
    assert j2["items"][0]["url"] == "https://imrantauqir.com/a1"

    monkeypatch.setattr(a.sw_decisions, "SITE_URL", "")


def test_feed_falls_back_to_library_when_no_html_exists(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(a.sw_decisions, "SITE_URL", "")
    _seed(tmp_path, "no-html", html=False)
    c = a.app.test_client()
    item = c.get("/feed.json").get_json()["items"][0]
    assert item["url"].endswith("/library")
    assert "content_html" not in item and item["content_text"]


def test_feed_json_has_cors_and_cache_headers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    c = a.app.test_client()
    r = c.get("/feed.json")
    assert r.headers["Access-Control-Allow-Origin"] == "*"
    assert "max-age" in r.headers["Cache-Control"]
    assert r.headers["Content-Type"].startswith("application/feed+json")


def test_feed_rss_is_well_formed_xml_with_full_content(tmp_path: Path, monkeypatch):
    import xml.etree.ElementTree as ET
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(a.sw_decisions, "SITE_URL", "")
    _seed(tmp_path, "a1", images=[{"url": "https://cdn.test/img/real.png"}])
    c = a.app.test_client()
    r = c.get("/feed.xml")
    assert r.mimetype == "application/rss+xml"
    text = r.get_data(as_text=True)
    root = ET.fromstring(text)            # raises if malformed
    assert root.tag == "rss"
    channel = root.find("channel")
    items = channel.findall("item")
    assert len(items) == 1
    assert items[0].find("title").text == "A1"
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    encoded = items[0].find("content:encoded", ns)
    assert encoded is not None and "<h1>a1</h1>" in encoded.text
    enclosure = items[0].find("enclosure")
    assert enclosure is not None and enclosure.get("url") == "https://cdn.test/img/real.png"
    pub_date = items[0].find("pubDate").text
    assert re.match(r"^[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} ", pub_date)


def test_embed_js_is_self_contained_and_points_at_the_feed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    c = a.app.test_client()
    r = c.get("/embed.js")
    assert r.mimetype == "application/javascript"
    js = r.get_data(as_text=True)
    assert "/feed.json" in js
    assert "humanly-articles" in js            # default target selector
    assert "data-limit" in js and "data-target" in js
    assert r.headers["Access-Control-Allow-Origin"] == "*"


def test_feed_items_skips_unreadable_meta_without_crashing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    (tmp_path / "broken_meta.json").write_text("not json", encoding="utf-8")
    _seed(tmp_path, "ok")
    c = a.app.test_client()
    j = c.get("/feed.json").get_json()
    assert [it["id"] for it in j["items"]] == ["ok"]
