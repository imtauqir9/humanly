"""Tests for the security hardening: secrets never in URLs, sandboxed generated
files, callbacks only to public addresses, drafts kept out of the public feed,
and a per-account sign-in lockout."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")


def make_app(tmp, password="a-long-test-password"):
    os.environ["APP_PASSWORD"] = password
    os.environ["APP_USERNAME"] = "admin"
    sys.modules.pop("app", None)
    import app as m
    m.OUTPUT_DIR = Path(tmp)
    m.APP_PASSWORD = password
    m.app.config["TESTING"] = True
    m._start_workers = lambda: None
    m._login_failures.clear()
    return m


def test_a_temporary_password_never_appears_in_a_url():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        c = m.app.test_client()
        c.post("/login", data={"password": "a-long-test-password"})
        r = c.post("/admin", data={"action": "create_user", "username": "sam@studio.example"})
        assert r.status_code == 302 and "password" not in r.headers["Location"].lower(), r.headers["Location"]
        page = c.get(r.headers["Location"]).data.decode()
        assert "Temporary password" in page, "shown once, on the page"
        assert "Temporary password" not in c.get("/admin").data.decode(), "and only once"


def test_generated_files_are_served_in_a_sandbox():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        (Path(d) / "post.html").write_text("<script>steal()</script>", encoding="utf-8")
        (Path(d) / "post_diagram_1.svg").write_text("<svg onload='steal()'/>", encoding="utf-8")
        c = m.app.test_client()
        c.post("/login", data={"password": "a-long-test-password"})
        for name in ("post.html", "post_diagram_1.svg"):
            csp = c.get(f"/output/{name}").headers.get("Content-Security-Policy", "")
            assert csp.startswith("sandbox") and "default-src 'none'" in csp, (name, csp)
        assert "sandbox" not in c.get("/library").headers.get("Content-Security-Policy", "")


def test_a_callback_to_a_private_address_is_never_sent(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        import requests
        sent = []
        monkeypatch.setattr(requests, "post", lambda *a, **kw: sent.append(a))
        m._post_callback("http://169.254.169.254/latest/meta-data/", {"x": 1})
        m._post_callback("http://127.0.0.1:8080/api/start", {"x": 1})
        assert sent == []


def test_drafts_stay_out_of_the_studio_feed_but_older_articles_remain():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        for slug in ("older", "new-draft", "new-live"):
            (Path(d) / f"{slug}_meta.json").write_text(json.dumps({"seo_meta": {"title": slug}}), encoding="utf-8")
        default = m.store().workspace("default")
        m.store().set_status(default["id"], "new-draft", "draft", "t")
        m.store().set_status(default["id"], "new-live", "published", "t")
        titles = sorted(i["title"] for i in m.app.test_client().get("/feed.json").get_json()["items"])
        assert titles == ["new-live", "older"], titles


def test_one_account_is_locked_after_guesses_from_many_addresses():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        c = m.app.test_client()
        for i in range(m._ACCOUNT_MAX_ATTEMPTS):
            c.post("/login", data={"username": "admin", "password": "guess"},
                   environ_base={"REMOTE_ADDR": f"203.0.113.{i}"})
        r = c.post("/login", data={"username": "admin", "password": "a-long-test-password"},
                   environ_base={"REMOTE_ADDR": "198.51.100.7"})
        assert b"Too many attempts" in r.data
        m._login_failures.clear()
