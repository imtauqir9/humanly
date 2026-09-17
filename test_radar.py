"""Tests for the topic radar: forum readers, theme cleaning, output files, the
end-to-end run with every network call faked, and the app's routes."""
import json
import os
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sw.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


# --- forums ----------------------------------------------------------------

def test_hn_top_dedupes_across_queries_and_ranks_by_attention(monkeypatch):
    hits = {"hits": [
        {"objectID": "1", "title": "Small story", "url": "https://a.test/1", "points": 10, "num_comments": 2, "created_at": "2026-09-10T00:00:00Z"},
        {"objectID": "2", "title": "Big story", "url": "", "points": 500, "num_comments": 300, "created_at": "2026-09-11T00:00:00Z"},
    ]}
    calls = []
    monkeypatch.setattr(sw.requests, "get", lambda url, **kw: (calls.append(kw["params"]["query"]), _Resp(payload=hits))[1])
    out = sw._hn_top(14)
    assert len(calls) == len(sw.RADAR_HN_QUERIES)
    assert [o["title"] for o in out] == ["Big story", "Small story"]       # deduped, ranked
    assert out[0]["url"] == "https://news.ycombinator.com/item?id=2"         # no url -> discussion
    assert out[0]["date"] == "2026-09-11" and out[0]["signal"] == 500


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>DeepSeek V4 is out</title>
    <link href="https://www.reddit.com/r/LocalLLaMA/comments/1/x/"/>
    <updated>2026-09-11T10:00:00+00:00</updated>
    <content type="html">&lt;a href="https://x.test/p?a=1&amp;amp;b=2"&gt;[link]&lt;/a&gt; &lt;a href="https://www.reddit.com/r/LocalLLaMA/comments/1/x/"&gt;[comments]&lt;/a&gt;</content>
  </entry>
  <entry>
    <title>Self post</title>
    <link href="https://www.reddit.com/r/LocalLLaMA/comments/2/y/"/>
    <updated>2026-09-10T10:00:00+00:00</updated>
    <content type="html">text only</content>
  </entry>
</feed>"""


class _Feed:
    def __init__(self, status=200, body=b""):
        self.status_code, self.content, self.text = status, body, body.decode("utf-8", "ignore")


def test_reddit_reads_the_feed_and_skips_blocked_subreddits(monkeypatch, capsys):
    def fake_get(url, **kw):
        if "MachineLearning" in url:
            return _Feed(status=403, body=b"<body>blocked</body>")
        assert url.endswith("/top/.rss") and kw["params"]["t"] == "week"
        return _Feed(body=FEED.encode("utf-8"))
    monkeypatch.setattr(sw.requests, "get", fake_get)
    monkeypatch.setattr(sw, "REDDIT_PAUSE_SECS", 0)
    out = sw._reddit_top(7)
    assert "r/MachineLearning: HTTP 403, skipped" in capsys.readouterr().out
    first = next(o for o in out if o["source"] == "r/LocalLLaMA")
    assert first["title"] == "DeepSeek V4 is out"
    assert first["url"] == "https://x.test/p?a=1&b=2"                      # link post -> target, unescaped
    assert first["discussion"] == "https://www.reddit.com/r/LocalLLaMA/comments/1/x/"
    assert first["date"] == "2026-09-11" and first["signal"].startswith("top 1 of the week")
    second = [o for o in out if o["source"] == "r/LocalLLaMA"][1]
    assert second["url"] == second["discussion"]                              # self post -> thread


# --- cleaning --------------------------------------------------------------

SIGNALS = [
    {"source": "Hacker News", "kind": "forum", "title": "Agents lying", "url": "https://hn.test/a", "discussion": "https://news.ycombinator.com/item?id=9", "signal": 300, "comments": 200, "date": "", "gist": ""},
    {"source": "Latent Space", "kind": "podcast", "title": "Agent evals episode", "url": "https://pod.test/ep/", "discussion": "", "signal": "unknown", "comments": 0, "date": "2026-09-08", "gist": "evals"},
    {"source": "Fireship", "kind": "youtube", "title": "AI agents in 100s", "url": "https://youtube.test/v", "discussion": "", "signal": "1.2M views", "comments": 0, "date": "2026-09-09", "gist": ""},
]


def test_clean_radar_keeps_only_evidence_it_saw_and_needs_two_sources():
    raw = {"themes": [
        {"title": "Agent reliability", "score": "88", "saturation": "LOW",
         "evidence": [{"url": "https://hn.test/a"}, {"url": "https://POD.test/ep", "signal": "new"},
                      {"url": "https://madeup.test/x"}],
         "suggested_take": ["I think evals are the job", "", 3]},
        {"title": "One-source theme", "score": 95, "evidence": [{"url": "https://youtube.test/v"}]},
        {"title": "Discussion-link theme", "score": 40,
         "evidence": [{"url": "https://news.ycombinator.com/item?id=9"}, {"url": "https://youtube.test/v"}]},
        "junk",
    ], "skipped": ["GPT-6 launch: product news", ""]}
    out = sw._clean_radar(raw, SIGNALS)
    titles = [t["title"] for t in out["themes"]]
    assert titles == ["Agent reliability", "Discussion-link theme"]
    top = out["themes"][0]
    assert [e["url"] for e in top["evidence"]] == ["https://hn.test/a", "https://pod.test/ep/"]
    assert top["evidence"][1]["signal"] == "new" and top["evidence"][0]["signal"] == "300"
    assert top["score"] == 88 and top["saturation"] == "low"
    assert top["suggested_take"] == ["I think evals are the job", "3"]
    assert out["skipped"] == ["GPT-6 launch: product news"]
    assert sw._clean_radar("garbage", SIGNALS) == {"themes": [], "skipped": []}


# --- output ----------------------------------------------------------------

def test_write_radar_writes_dated_files_and_latest(tmp_path: Path):
    radar = {"themes": [{"title": "T", "why_now": "now", "who_is_talking": "pods", "evidence": [
        {"source": "HN", "title": "e", "url": "https://hn.test/a", "signal": "300"}],
        "saturation": "low", "engineer_angle": "angle", "suggested_title": "Title",
        "suggested_intent": "intent", "suggested_take": ["I think"], "score": 70}], "skipped": ["x"]}
    md, js = sw.write_radar(radar, tmp_path, 14, 57)
    stamp = sw.TODAY.strftime("%Y-%m-%d")
    assert md.name == f"radar_{stamp}.md" and js.name == f"radar_{stamp}.json"
    latest = json.loads((tmp_path / "radar_latest.json").read_text(encoding="utf-8"))
    assert latest["signals"] == 57 and latest["themes"][0]["title"] == "T"
    text = md.read_text(encoding="utf-8")
    assert "## 1. T" in text and "**Working title:** Title" in text and "- I think" in text
    assert "[e](https://hn.test/a)" in text and "## Left out" in text


def test_run_radar_end_to_end_with_everything_faked(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(sw, "_hn_top", lambda days, limit=40: [SIGNALS[0]])
    monkeypatch.setattr(sw, "_reddit_top", lambda days, limit=40: [])
    monkeypatch.setattr(sw, "_radar_web_scan", lambda days: SIGNALS[1:])
    seen = {}

    def fake_claude(prompt, **kw):
        seen["prompt"] = prompt
        return json.dumps({"themes": [{"title": "Agent reliability", "score": 80, "saturation": "low",
                                       "evidence": [{"url": "https://hn.test/a"}, {"url": "https://pod.test/ep/"}],
                                       "why_now": "w", "engineer_angle": "a", "suggested_title": "s",
                                       "suggested_intent": "i", "suggested_take": ["I think x"]}], "skipped": []})
    monkeypatch.setattr(sw, "call_claude", fake_claude)
    md, js = sw.run_radar(tmp_path, days=14)
    out = capsys.readouterr().out
    assert "Synthesising 3 signals" in out and "[ 80] Agent reliability" in out
    assert "https://hn.test/a" in seen["prompt"] and "1.2M views" in seen["prompt"]
    assert sw.RADAR_LENS in seen["prompt"]
    assert md.exists() and js.exists() and (tmp_path / "radar_latest.json").exists()


def test_web_scan_drops_items_without_real_urls(monkeypatch):
    monkeypatch.setattr(sw, "_claude_web_call", lambda *a, **kw: {"items": [
        {"kind": "youtube", "title": "ok", "url": "https://yt.test/1", "who": "Fireship", "signal": "2M views"},
        {"kind": "podcast", "title": "no url", "url": "n/a"},
        {"title": "", "url": "https://x.test"},
        "junk",
    ]})
    items = sw._radar_web_scan(14)
    assert [i["title"] for i in items] == ["ok"] and items[0]["source"] == "Fireship"


# --- app -------------------------------------------------------------------

def test_app_radar_routes(tmp_path: Path, monkeypatch):
    os.environ["APP_PASSWORD"] = ""
    import app as a
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    c = a.app.test_client()
    assert c.get("/api/radar/latest").get_json() == {"themes": [], "generated_at": None}
    (tmp_path / "radar_latest.json").write_text('{"themes": [{"title": "T"}], "generated_at": "2026-09-13T00:00:00Z"}', encoding="utf-8")
    assert c.get("/api/radar/latest").get_json()["themes"][0]["title"] == "T"

    spawned = {}
    monkeypatch.setattr(a, "_spawn", lambda cmd, callback=None, **kw: (spawned.update(cmd=cmd, callback=callback), "job-1")[1])
    r = c.post("/api/radar", json={"days": 999})
    assert r.get_json() == {"job_id": "job-1"}
    assert "--radar" in spawned["cmd"] and spawned["cmd"][spawned["cmd"].index("--radar-days") + 1] == "60"
    assert spawned["callback"] is None
    r = c.post("/api/radar", json={"callback_url": "notaurl"})
    assert r.status_code == 400
    r = c.post("/api/radar", json={"callback_url": "https://hooks.test/x", "external_id": "abc"})
    assert spawned["callback"]["kind"] == "radar" and spawned["callback"]["external_id"] == "abc"

    assert a._radar_is_stale() is False           # written just now
    (tmp_path / "radar_latest.json").write_text('{"generated_at": "2026-01-01T00:00:00Z"}', encoding="utf-8")
    assert a._radar_is_stale() is True
    with a.app.test_request_context("/"):
        payload = a._radar_payload({"external_id": "e", "base_url": ""}, "done", "")
    assert payload["kind"] == "radar" and payload["status"] == "done"
