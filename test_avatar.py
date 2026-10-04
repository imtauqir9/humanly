"""Tests for the author's avatar: a Tavus-rendered video of the script, and a
live conversation briefed on one article."""
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import seo_writer as sw  # noqa: E402

SCRIPT = "# Script\n\n## Hook\n**Visual:** a cluster\nKubernetes bills are mostly requests nobody uses.\n\n" \
         "## Narration only\n" + " ".join(["Requests decide the bill, so right-size them first."] * 6)


class _R:
    def __init__(self, payload=None, content=b"", status=200):
        self._payload, self.content, self.status_code = payload or {}, content, status
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sw.requests.HTTPError(f"{self.status_code}", response=self)

    def iter_content(self, n):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_tavus(monkeypatch, statuses, final=None):
    sent = {}
    queue = list(statuses)

    def post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, body=json, key=headers["x-api-key"])
        return _R({"video_id": "v123", "status": "queued"})

    def get(url, headers=None, timeout=None, stream=False):
        if url.endswith("/v123"):
            status = queue.pop(0) if queue else "ready"
            return _R({"status": status, "download_url": "https://cdn.tavus.example/v123.mp4",
                       "hosted_url": "https://videos.tavus.example/v123", **(final or {})})
        return _R(content=b"MP4DATA")

    monkeypatch.setattr(sw.requests, "post", post)
    monkeypatch.setattr(sw.requests, "get", get)
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)
    monkeypatch.setenv("TAVUS_API_KEY", "tk")
    monkeypatch.setenv("TAVUS_REPLICA_ID", "r-imran")
    return sent


def test_the_avatar_reads_the_narration_and_the_mp4_is_saved(tmp_path, monkeypatch):
    sent = fake_tavus(monkeypatch, ["queued", "generating", "ready"])
    path = sw.generate_avatar_video(SCRIPT, "k8s", tmp_path)
    assert path == tmp_path / "k8s_avatar.mp4" and path.read_bytes() == b"MP4DATA"
    assert sent["body"]["replica_id"] == "r-imran"
    assert sent["body"]["script"].startswith("Requests decide the bill"), "only the spoken lines"
    assert "**Visual:**" not in sent["body"]["script"]
    record = json.loads((tmp_path / "k8s_avatar.json").read_text(encoding="utf-8"))
    assert record["hosted_url"].endswith("/v123")


def test_without_tavus_keys_the_step_is_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVUS_API_KEY", raising=False)
    assert sw.generate_avatar_video(SCRIPT, "k8s", tmp_path) is None
    assert not list(tmp_path.iterdir())


def test_a_failed_render_does_not_fail_the_article(tmp_path, monkeypatch):
    fake_tavus(monkeypatch, ["generating", "error"], final={"status_details": "replica not ready"})
    assert sw.generate_avatar_video(SCRIPT, "k8s", tmp_path) is None
    assert not (tmp_path / "k8s_avatar.mp4").exists()


# --- the app ------------------------------------------------------------------

def make_app(tmp, avatar_url="https://imran-avatar.fly.dev"):
    os.environ["APP_PASSWORD"] = ""
    os.environ["AVATAR_URL"] = avatar_url
    sys.modules.pop("app", None)
    import app as m
    m.OUTPUT_DIR = Path(tmp)
    m.APP_PASSWORD = ""
    m.app.config["TESTING"] = True
    m._start_workers = lambda: None
    return m


def article(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "k8s.md").write_text(
        "👋 Hi everyone, Imran here.\n\n# Cutting Kubernetes costs\n\nRequests decide the bill.\n"
        "\n---\n\nThat's a wrap for this edition.\n", encoding="utf-8")
    (folder / "k8s_meta.json").write_text(json.dumps({"seo_meta": {
        "title": "Cutting Kubernetes costs", "description": "Where the bill comes from."}}), encoding="utf-8")
    (folder / "k8s_facts.json").write_text(json.dumps({"take": "I think most clusters are 3x oversized."}),
                                           encoding="utf-8")


def test_the_avatar_video_is_offered_in_the_studio_only(monkeypatch):
    monkeypatch.setenv("TAVUS_API_KEY", "tk")
    monkeypatch.setenv("TAVUS_REPLICA_ID", "r-imran")
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        spawned = {}
        m._spawn = lambda cmd, **kw: (spawned.update(cmd=cmd), "j")[1]
        c = m.app.test_client()
        assert "My avatar presents it" in c.get("/").data.decode()
        c.post("/api/start", json={"topic": "Cutting costs", "avatar": True})
        assert "--avatar" in spawned["cmd"]

        ws = m.store().create_workspace("Acme Cloud")
        c.get(f"/workspace/{ws['slug']}")
        assert "My avatar presents it" not in c.get("/").data.decode()
        c.post("/api/start", json={"topic": "Cutting costs", "avatar": True})
        assert "--avatar" not in spawned["cmd"], "a client's article is never presented by the studio's face"


def test_ask_imran_opens_the_avatar_with_a_briefing_it_can_fetch():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        article(Path(d))
        c = m.app.test_client()
        assert "Ask Imran about this" in c.get("/a/k8s").data.decode()
        r = c.get("/a/k8s/talk")
        assert r.status_code == 302
        target = urlparse(r.headers["Location"])
        assert f"{target.scheme}://{target.netloc}" == "https://imran-avatar.fly.dev"
        brief_url = parse_qs(target.query)["brief"][0]
        assert "/dl/" in brief_url, "a signed link, readable without signing in"
        brief = c.get(urlparse(brief_url).path).data.decode()
        assert "Cutting Kubernetes costs" in brief and "3x oversized" in brief
        assert "Hi everyone" not in brief and "That's a wrap" not in brief, "greeting and sign-off left out"


def test_no_avatar_button_for_a_client_or_without_an_avatar_url():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d, avatar_url="")
        article(Path(d))
        c = m.app.test_client()
        assert "Ask Imran" not in c.get("/a/k8s").data.decode()
        assert c.get("/a/k8s/talk").status_code == 404
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = m.store().create_workspace("Acme Cloud")
        article(m.ws_dir(ws))
        c = m.app.test_client()
        c.get(f"/workspace/{ws['slug']}")
        assert c.get("/a/k8s/talk").status_code == 404
