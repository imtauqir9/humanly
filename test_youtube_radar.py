"""The radar reads YouTube directly: the Data API with a key, the channel
pages without one, and the pages again when the API refuses."""
import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload or {}, text

    def json(self):
        return self._payload


def test_counts_and_ages_parse_the_forms_youtube_shows():
    assert sw._yt_count("1.4M") == 1_400_000
    assert sw._yt_count("1.4 million views") == 1_400_000
    assert sw._yt_count("12,345 views") == 12_345
    assert sw._yt_count("980K views") == 980_000
    assert sw._yt_count("") == 0
    assert sw._yt_age_days("1d ago") == 1
    assert sw._yt_age_days("3 days ago") == 3
    assert sw._yt_age_days("2 weeks ago") == 14
    assert sw._yt_age_days("1mo ago") == 30
    assert sw._yt_age_days("5 minutes ago") < 0.01
    assert sw._yt_age_days("Streamed live") is None


def _lockup(vid, title, views, age):
    return {"lockupViewModel": {"contentId": vid, "metadata": {"lockupMetadataViewModel": {
        "title": {"content": title},
        "metadata": {"contentMetadataViewModel": {"metadataRows": [{"metadataParts": [
            {"text": {"content": "x"}, "accessibilityLabel": views},
            {"text": {"content": "y"}, "accessibilityLabel": age}]}]}}}}}}


def _page(*tiles):
    data = {"contents": {"tabs": [{"items": list(tiles)}]}}
    return f"<script>var ytInitialData = {json.dumps(data)};</script>"


def test_channel_pages_keep_the_window_and_rank_by_views(monkeypatch):
    monkeypatch.setattr(sw, "RADAR_YOUTUBE_HANDLES", {"Fireship": "Fireship", "Gone": "gone"})
    old_style = {"videoRenderer": {"videoId": "c", "title": {"runs": [{"text": "Old shape"}]},
                                   "viewCountText": {"simpleText": "50K views"},
                                   "publishedTimeText": {"simpleText": "2 days ago"}}}

    def fake_get(url, **kw):
        if "@gone" in url:
            return _Resp(status=404)
        return _Resp(text=_page(_lockup("a", "Small one", "20 thousand views", "1 day ago"),
                                _lockup("b", "Big one", "1.4 million views", "3 days ago"),
                                _lockup("z", "Too old", "9 million views", "1 month ago"),
                                old_style))
    monkeypatch.setattr(sw.requests, "get", fake_get)
    out = sw._youtube_page_top(14)
    assert [v["title"] for v in out] == ["Big one", "Old shape", "Small one"]
    assert out[0]["url"] == "https://www.youtube.com/watch?v=b"
    assert out[0]["kind"] == "youtube" and out[0]["source"] == "Fireship"
    assert out[0]["signal"] == "1,400,000 views"


def test_data_api_reads_uploads_and_searches_with_exact_counts(monkeypatch):
    monkeypatch.setattr(sw, "RADAR_YOUTUBE_HANDLES", {"Fireship": "Fireship"})
    monkeypatch.setattr(sw, "RADAR_YOUTUBE_QUERIES", ["AI"])
    calls = []

    def fake_get(url, params=None, **kw):
        calls.append(url.rsplit("/", 1)[1])
        assert params["key"] == "k"
        if url.endswith("/channels"):
            assert params["forHandle"] == "@Fireship"
            return _Resp(payload={"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})
        if url.endswith("/playlistItems"):
            return _Resp(payload={"items": [
                {"contentDetails": {"videoId": "new", "videoPublishedAt": "2999-01-01T00:00:00Z"}},
                {"contentDetails": {"videoId": "old", "videoPublishedAt": "2000-01-01T00:00:00Z"}}]})
        if url.endswith("/search"):
            assert params["order"] == "viewCount" and params["type"] == "video"
            return _Resp(payload={"items": [{"id": {"videoId": "viral"}, "snippet": {"channelTitle": "Someone"}}]})
        if url.endswith("/videos"):
            assert set(params["id"].split(",")) == {"new", "viral"}          # the old upload is dropped
            return _Resp(payload={"items": [
                {"id": "new", "snippet": {"title": "New upload", "channelTitle": "Fireship",
                                          "publishedAt": "2026-09-20T00:00:00Z", "description": "A  short\n one"},
                 "statistics": {"viewCount": "5000", "commentCount": "40"}},
                {"id": "viral", "snippet": {"title": "Viral", "channelTitle": "Someone", "publishedAt": "2026-09-21T00:00:00Z"},
                 "statistics": {"viewCount": "900000"}}]})
        raise AssertionError(url)
    monkeypatch.setattr(sw.requests, "get", fake_get)
    out = sw._youtube_api_top(14, "k")
    assert [v["title"] for v in out] == ["Viral", "New upload"]
    assert out[1]["comments"] == 40 and out[1]["gist"] == "A short one" and out[1]["date"] == "2026-09-20"


def test_falls_back_to_the_pages_when_the_api_refuses(monkeypatch, capsys):
    monkeypatch.setattr(sw, "YOUTUBE_API_KEY", "bad")
    monkeypatch.setattr(sw, "_youtube_api_top", lambda days, key: (_ for _ in ()).throw(sw.ClaudeError("quota exceeded")))
    monkeypatch.setattr(sw, "_youtube_page_top", lambda days: [{"title": "from pages"}])
    assert sw._youtube_top(14) == [{"title": "from pages"}]
    assert "reading the channel pages instead" in capsys.readouterr().out


def test_no_key_goes_straight_to_the_pages(monkeypatch):
    monkeypatch.setattr(sw, "YOUTUBE_API_KEY", "")
    monkeypatch.setattr(sw, "_youtube_api_top", lambda days, key: (_ for _ in ()).throw(AssertionError("no key")))
    monkeypatch.setattr(sw, "_youtube_page_top", lambda days: [])
    assert sw._youtube_top(14) == []


def test_radar_run_carries_youtube_and_drops_the_web_duplicate(monkeypatch, tmp_path):
    video = sw._yt_item("Fireship", "v1", "Agents in 100s", 1_200_000, "2026-09-20")
    monkeypatch.setattr(sw, "_hn_top", lambda days, limit=40: [])
    monkeypatch.setattr(sw, "_reddit_top", lambda days, limit=40: [])
    monkeypatch.setattr(sw, "_youtube_top", lambda days: [video])
    seen = {}

    def web(days, have_channels=False):
        seen["have_channels"] = have_channels
        return [dict(video, signal="unknown", source="web"),
                {"source": "Latent Space", "kind": "podcast", "title": "Ep", "url": "https://p.test",
                 "discussion": "", "signal": "unknown", "comments": 0, "date": "", "gist": ""}]
    monkeypatch.setattr(sw, "_radar_web_scan", web)
    got = {}
    monkeypatch.setattr(sw, "synthesize_radar", lambda signals, days, decisions=None: (got.update(signals=signals), {"themes": []})[1])
    monkeypatch.setattr(sw, "write_usage", lambda *a, **k: tmp_path / "u.json")
    sw.run_radar(tmp_path, 14)
    assert seen["have_channels"] is True
    urls = [s["url"] for s in got["signals"]]
    assert urls.count("https://www.youtube.com/watch?v=v1") == 1
    assert got["signals"][0]["signal"] == "1,200,000 views"


def test_each_channel_keeps_only_its_top_few(monkeypatch):
    monkeypatch.setattr(sw, "RADAR_YOUTUBE_HANDLES", {"Big": "big", "Small": "small"})
    monkeypatch.setattr(sw, "RADAR_YOUTUBE_PER_CHANNEL", 2)

    def fake_get(url, **kw):
        if "@big" in url:
            return _Resp(text=_page(*[_lockup(f"b{i}", f"Big {i}", f"{i} million views", "1 day ago") for i in range(1, 6)]))
        return _Resp(text=_page(_lockup("s1", "Small one", "9 thousand views", "2 days ago")))
    monkeypatch.setattr(sw.requests, "get", fake_get)
    out = sw._youtube_page_top(14)
    assert [v["title"] for v in out] == ["Big 5", "Big 4", "Small one"]
