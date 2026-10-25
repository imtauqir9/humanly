"""Tests for sending articles to a client's WordPress, against a fake WordPress."""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import wordpress as wpress  # noqa: E402

HTML = """<html><head><title>T</title><script type="application/ld+json">{}</script></head><body>
<h1>Cutting Kubernetes costs</h1><p>Requests decide the bill.</p>
<figure class="diagram"><svg viewBox="0 0 10 10"><rect/></svg><figcaption>Diagram: how requests add up</figcaption></figure>
<p>More text.</p></body></html>"""


class _R:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeWP:
    """Records every call; answers like WordPress would."""
    def __init__(self, login_ok=True):
        self.calls, self.login_ok, self.next_id = [], login_ok, 100

    def request(self, method, url, auth=None, timeout=None, **kw):
        self.calls.append((method, url.split("/wp-json/wp/v2")[-1], kw))
        if not self.login_ok:
            return _R(401, {"code": "incorrect_password", "message": "bad"})
        path = url.split("/wp-json/wp/v2")[-1]
        if path.startswith("/users/me"):
            return _R(200, {"name": "Ed Itor", "capabilities": {"publish_posts": True, "upload_files": True}})
        if path == "/media":
            self.next_id += 1
            return _R(201, {"id": self.next_id, "source_url": f"https://acme.example/wp-content/uploads/d{self.next_id}.png"})
        if path.startswith("/media/"):
            return _R(200, {"id": int(path.rsplit("/", 1)[1])})
        if path == "/posts":
            return _R(201, {"id": 555, "link": "https://acme.example/?p=555", "status": kw["json"]["status"]})
        if path.startswith("/posts/"):
            return _R(200, {"id": int(path.rsplit("/", 1)[1]), "link": "https://acme.example/k8s-costs/",
                            "status": kw["json"]["status"]})
        return _R(404, {"message": "no route"})


@pytest.fixture(autouse=True)
def public_everywhere(monkeypatch):
    monkeypatch.setattr(wpress, "_check_public", lambda url: None)


def article_dir(tmp: Path) -> Path:
    (tmp / "k8s-costs.html").write_text(HTML, encoding="utf-8")
    (tmp / "k8s-costs_meta.json").write_text(json.dumps({"seo_meta": {
        "title": "Cutting Kubernetes costs", "description": "Where the bill comes from."}}), encoding="utf-8")
    (tmp / "k8s-costs_diagram_1.png").write_bytes(b"\x89PNG fake")
    return tmp


def test_an_article_arrives_as_a_post_with_its_diagram_and_excerpt(tmp_path):
    fake = FakeWP()
    wp = wpress.WordPress("acme.example", "ed", "abcd efgh ijkl", session=fake)
    result = wpress.publish_article(wp, article_dir(tmp_path), "k8s-costs", status="draft")
    assert result == {"id": 555, "link": "https://acme.example/?p=555", "status": "draft"}
    post = [c for c in fake.calls if c[1] == "/posts"][0][2]["json"]
    assert post["title"] == "Cutting Kubernetes costs" and post["excerpt"] == "Where the bill comes from."
    assert post["slug"] == "k8s-costs" and post["featured_media"] == 101
    assert "<h1" not in post["content"], "WordPress prints the title itself"
    assert "<svg" not in post["content"] and "d101.png" in post["content"], "the diagram is an uploaded image"
    assert "how requests add up" in post["content"], "the caption survives"
    assert "<script" not in post["content"]


def test_sending_again_updates_the_same_post_without_reuploading(tmp_path):
    fake = FakeWP()
    wp = wpress.WordPress("https://acme.example", "ed", "pw", session=fake)
    cache = {}
    wpress.publish_article(wp, article_dir(tmp_path), "k8s-costs", media_cache=cache)
    uploads = sum(1 for c in fake.calls if c[1] == "/media")
    result = wpress.publish_article(wp, tmp_path, "k8s-costs", status="publish", post_id=555, media_cache=cache)
    assert sum(1 for c in fake.calls if c[1] == "/media") == uploads, "no duplicate media"
    assert result["status"] == "publish" and result["link"].endswith("/k8s-costs/")
    assert any(c[1] == "/posts/555" for c in fake.calls)


def test_a_wrong_password_reads_as_a_wrong_password(tmp_path):
    wp = wpress.WordPress("https://acme.example", "ed", "nope", session=FakeWP(login_ok=False))
    with pytest.raises(wpress.WordPressError, match="refused the login"):
        wp.whoami()


def test_a_private_address_is_refused(monkeypatch):
    import site_intake
    monkeypatch.setattr(wpress, "_check_public", site_intake._check_public)
    wp = wpress.WordPress("http://127.0.0.1", "ed", "pw", session=FakeWP())
    with pytest.raises(wpress.WordPressError, match="Refusing"):
        wp.whoami()


# --- the app ------------------------------------------------------------------

def make_app(tmp):
    os.environ["APP_PASSWORD"] = "s3cret"
    os.environ["APP_USERNAME"] = "admin"
    sys.modules.pop("app", None)
    import app as m
    m.OUTPUT_DIR = Path(tmp)
    m.APP_PASSWORD = "s3cret"
    m.app.config["TESTING"] = True
    m._start_workers = lambda: None
    return m


def h(user, pw="correct-horse-1"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_publishing_waits_for_approval_then_marks_the_article_live(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        s = m.store()
        ws = s.create_workspace("Acme Cloud", {"require_approval": True, "wp_url": "https://acme.example",
                                               "wp_user": "ed", "wp_status": "publish"})
        s.set_secret(ws["id"], m.WP_SECRET, "app pass word")
        ed = s.create_user("editor", "correct-horse-1")
        s.set_role(ed["id"], ws["id"], "editor")
        folder = m.ws_dir(ws)
        folder.mkdir(parents=True)
        article_dir(folder)
        (folder / "k8s-costs.md").write_text("# Cutting Kubernetes costs\n\nBody text.", encoding="utf-8")
        s.set_status(ws["id"], "k8s-costs", "in_review", "writer")
        fake = FakeWP()
        monkeypatch.setattr(m.wpress, "_check_public", lambda url: None)
        real = m.wpress.WordPress
        monkeypatch.setattr(m.wpress, "WordPress", lambda *a, **kw: real(*a, session=fake))
        c = m.app.test_client()

        r = c.post("/a/k8s-costs/publish", headers=h("editor"))
        assert "approved" in r.headers["Location"], "not before approval"
        assert not any(call[1] == "/posts" for call in fake.calls)

        s.set_status(ws["id"], "k8s-costs", "approved", "client")
        r = c.post("/a/k8s-costs/publish", headers=h("editor"))
        assert "msg=" in r.headers["Location"], r.headers["Location"]
        state = s.article_state(ws["id"], "k8s-costs")
        assert state["status"] == "published" and state["wp_post_id"] == 555
        assert any("Sent in WordPress as publish" in x["body"] for x in s.comments(ws["id"], "k8s-costs"))
        feed = c.get(f"/feed.json?ws={ws['slug']}").get_json()
        assert [i["title"] for i in feed["items"]] == ["Cutting Kubernetes costs"]


def test_the_application_password_is_stored_encrypted():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        c = m.app.test_client()
        c.post("/login", data={"password": "s3cret"})
        c.post("/settings", data={"action": "wordpress", "wp_url": "https://acme.example", "wp_user": "ed",
                                  "wp_password": "abcd efgh ijkl mnop", "wp_status": "draft"})
        raw = (Path(d) / "_system" / "humanly.db").read_bytes()
        assert b"abcd efgh" not in raw, "never in the database in the clear"
        assert m.store().get_secret(m.store().workspace("default")["id"], m.WP_SECRET) == "abcd efgh ijkl mnop"
        page = c.get("/settings").data.decode()
        assert "abcd efgh" not in page and "Saved" in page


def test_without_wordpress_an_editor_marks_it_published_by_hand():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        s = m.store()
        ws = s.create_workspace("Acme Cloud", {"require_approval": True})
        ed = s.create_user("editor", "correct-horse-1")
        s.set_role(ed["id"], ws["id"], "editor")
        folder = m.ws_dir(ws)
        folder.mkdir(parents=True)
        (folder / "k8s-costs.md").write_text("# T\n\nBody.", encoding="utf-8")
        s.set_status(ws["id"], "k8s-costs", "approved", "client")
        c = m.app.test_client()
        assert "Mark as published" in c.get("/a/k8s-costs", headers=h("editor")).data.decode()
        c.post("/a/k8s-costs/status", data={"status": "published"}, headers=h("editor"))
        assert s.article_state(ws["id"], "k8s-costs")["status"] == "published"
