"""Tests for dig in: reading forum threads by code, cleaning the brief, saving it
onto the radar, and the app route."""
import json
import os
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402


class _Resp:
    def __init__(self, status=200, payload=None, body=b""):
        self.status_code, self._payload, self.content = status, payload or {}, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sw.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


HN_ITEM = {"title": "Story", "children": [
    {"author": "alice", "text": "<p>This is a long enough comment about agents that says something real, with &quot;quotes&quot; in it.</p>",
     "children": [{"author": "bob", "text": "<p>A reply that is also long enough to count as a real contribution to this comment thread.</p>",
                   "children": [{"author": "carol", "text": "<p>Too deep: this third-level reply should be ignored even though it is long enough.</p>", "children": []}]}]},
    {"author": "dave", "text": "<p>short</p>", "children": []},
]}


def test_hn_comments_flatten_two_levels_and_strip_html(monkeypatch):
    monkeypatch.setattr(sw.requests, "get", lambda url, **kw: _Resp(payload=HN_ITEM))
    out = sw._hn_comments("https://news.ycombinator.com/item?id=123")
    assert len(out) == 2
    assert out[0].startswith('alice: This is a long enough comment') and '"quotes"' in out[0]
    assert out[1].startswith("bob:")
    assert sw._hn_comments("https://example.com/not-hn") == []
    monkeypatch.setattr(sw.requests, "get", lambda url, **kw: _Resp(status=500))
    assert sw._hn_comments("https://news.ycombinator.com/item?id=9") == []


THREAD = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><author><name>/u/op</name></author><title>The post</title><content type="html">the post body itself, long enough to pass the filter</content></entry>
  <entry><author><name>/u/eve</name></author><content type="html">&lt;p&gt;I ran this in production and the retry storm took the cluster down twice.&lt;/p&gt;</content></entry>
  <entry><author><name>/u/x</name></author><content type="html">lol</content></entry>
</feed>"""


def test_reddit_comments_skip_the_post_and_tolerate_blocks(monkeypatch):
    monkeypatch.setattr(sw, "REDDIT_PAUSE_SECS", 0)
    monkeypatch.setattr(sw.requests, "get", lambda url, **kw: _Resp(body=THREAD.encode("utf-8")))
    out = sw._reddit_comments("https://www.reddit.com/r/LocalLLaMA/comments/1/x/")
    assert out == ["/u/eve: I ran this in production and the retry storm took the cluster down twice."]
    monkeypatch.setattr(sw.requests, "get", lambda url, **kw: _Resp(status=429, body=b"<body>"))
    assert sw._reddit_comments("https://www.reddit.com/r/LocalLLaMA/comments/1/x/") == []
    assert sw._reddit_comments("https://news.ycombinator.com/item?id=1") == []


def test_gather_discussions_routes_by_host(monkeypatch):
    monkeypatch.setattr(sw, "_hn_comments", lambda d, limit=30: ["a: hn comment"])
    monkeypatch.setattr(sw, "_reddit_comments", lambda d, limit=20: [])
    theme = {"evidence": [
        {"title": "HN one", "url": "https://x.test", "discussion": "https://news.ycombinator.com/item?id=1"},
        {"title": "Reddit one", "url": "https://y.test", "discussion": "https://www.reddit.com/r/a/comments/1/"},
        {"title": "Video", "url": "https://yt.test", "discussion": ""},
    ]}
    text = sw._gather_discussions(theme)
    assert "=== Discussion of: HN one" in text and "- a: hn comment" in text
    assert "Reddit one" not in text and "Video" not in text


def test_clean_dig_drops_rows_without_real_urls_and_caps():
    raw = {
        "summary": "  what it   is ",
        "claims": [{"claim": "c", "who": "w", "url": "https://a.test", "quote": "q"},
                   {"claim": "no url", "who": "w", "url": "n/a", "quote": "q"}, "junk"],
        "counterarguments": [{"point": f"p{i}", "who": "w", "url": "https://a.test"} for i in range(12)],
        "numbers": [{"value": "", "what": "", "url": "https://a.test"}],
        "linkedin": [{"who": "Jane, CTO", "gist": "g", "url": "https://www.linkedin.com/posts/x"}],
        "unanswered": ["q1", "", 7],
        "suggested_take": ["I think", ""],
        "sources_opened": ["https://a.test", "junk"],
    }
    out = sw._clean_dig(raw)
    assert out["summary"] == "what it is"
    assert len(out["claims"]) == 1 and len(out["counterarguments"]) == 8
    assert out["numbers"] == [] and out["linkedin"][0]["who"] == "Jane, CTO"
    assert out["unanswered"] == ["q1", "7"] and out["suggested_take"] == ["I think"]
    assert out["sources_opened"] == ["https://a.test"]
    assert sw._clean_dig("garbage")["claims"] == []


BRIEF = {"summary": "S", "claims": [{"claim": "c", "who": "w", "url": "https://a.test", "quote": "q"}],
         "counterarguments": [], "practitioners_said": [], "numbers": [], "linkedin": [],
         "unanswered": ["why?"], "sharper_angle": "sharper", "suggested_title": "Better title",
         "suggested_intent": "", "suggested_take": ["I'd say"], "sources_opened": ["https://a.test"]}


def test_write_brief_attaches_to_the_theme_in_latest_and_dated(tmp_path: Path):
    stamp = sw.TODAY.strftime("%Y-%m-%d")
    radar = {"themes": [{"title": "T1", "suggested_intent": "keep me", "suggested_take": ["old"]}, {"title": "T2"}]}
    for name in ("radar_latest.json", f"radar_{stamp}.json"):
        (tmp_path / name).write_text(json.dumps(radar), encoding="utf-8")
    md, js = sw.write_brief(1, radar["themes"][0], BRIEF, tmp_path)
    assert md.name == f"radar_{stamp}_brief_1.md" and js.exists()
    text = md.read_text(encoding="utf-8")
    assert "# Brief: T1" in text and "**Sharper angle.** sharper" in text and "## Nobody answers" in text
    for name in ("radar_latest.json", f"radar_{stamp}.json"):
        saved = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        b = saved["themes"][0]["brief"]
        assert b["file"] == md.name and b["suggested_title"] == "Better title"
        assert b["suggested_intent"] == "keep me"           # falls back to the theme's
        assert b["suggested_take"] == ["I'd say"] and b["counts"]["claims"] == 1
        assert "brief" not in saved["themes"][1]


def test_run_dig_end_to_end(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "radar_latest.json").write_text(json.dumps({"themes": [
        {"title": "Agent collusion", "why_now": "w", "engineer_angle": "a", "score": 88,
         "evidence": [{"source": "HN", "title": "e", "url": "https://x.test", "discussion": "https://news.ycombinator.com/item?id=1"}]}]}),
        encoding="utf-8")
    monkeypatch.setattr(sw, "_gather_discussions", lambda theme: "=== Discussion ===\n- a: said things")
    seen = {}
    monkeypatch.setattr(sw, "_claude_web_call", lambda prompt, **kw: (seen.update(prompt=prompt, kw=kw), BRIEF)[1])
    md, js = sw.run_dig(tmp_path, 1)
    out = capsys.readouterr().out
    assert "Theme   : 1. Agent collusion" in out and "Claims 1" in out
    assert "site:linkedin.com/posts" in seen["prompt"] and "a: said things" in seen["prompt"]
    assert seen["kw"]["schema"] == sw.DIG_SCHEMA
    assert json.loads((tmp_path / "radar_latest.json").read_text(encoding="utf-8"))["themes"][0]["brief"]["file"] == md.name
    import pytest
    with pytest.raises(sw.ClaudeError):
        sw.run_dig(tmp_path, 5)


def test_radar_evidence_keeps_the_discussion_link():
    signals = [{"source": "Hacker News", "kind": "forum", "title": "a", "url": "https://a.test", "discussion": "https://news.ycombinator.com/item?id=1", "signal": 1, "comments": 0, "date": "", "gist": ""},
               {"source": "Fireship", "kind": "youtube", "title": "b", "url": "https://b.test", "discussion": "", "signal": "1M", "comments": 0, "date": "", "gist": ""}]
    out = sw._clean_radar({"themes": [{"title": "t", "score": 5, "evidence": [{"url": "https://a.test"}, {"url": "https://b.test"}]}]}, signals)
    assert out["themes"][0]["evidence"][0]["discussion"] == "https://news.ycombinator.com/item?id=1"
    assert out["themes"][0]["evidence"][1]["discussion"] == ""


def test_app_dig_route(tmp_path: Path, monkeypatch):
    os.environ["APP_PASSWORD"] = ""
    import app as a
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    c = a.app.test_client()
    assert c.post("/api/radar/dig", json={"index": 1}).status_code == 400          # no radar yet
    (tmp_path / "radar_latest.json").write_text('{"themes": [{"title": "T"}]}', encoding="utf-8")
    assert c.post("/api/radar/dig", json={"index": 0}).status_code == 400
    spawned = {}
    monkeypatch.setattr(a, "_spawn", lambda cmd, **kw: (spawned.update(cmd=cmd), "job-2")[1])
    assert c.post("/api/radar/dig", json={"index": 2}).get_json() == {"job_id": "job-2"}
    assert spawned["cmd"][spawned["cmd"].index("--dig") + 1] == "2"
    html = c.get("/").get_data(as_text=True)
    assert "class=\"radar-dig\"" in html and "async function digTheme" in html
