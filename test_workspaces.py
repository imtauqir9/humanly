"""Tests for client workspaces: who can see and do what, and that one client's
work never leaks into another's."""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")


def make_app(tmp, password="s3cret"):
    os.environ["APP_PASSWORD"] = password
    os.environ["APP_USERNAME"] = "admin"
    sys.modules.pop("app", None)
    import app as m
    m.OUTPUT_DIR = Path(tmp)
    m.APP_PASSWORD = password
    m.app.config["TESTING"] = True
    m._start_workers = lambda: None
    return m


def basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def article(folder: Path, slug: str, title: str):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{slug}_meta.json").write_text(json.dumps({"seo_meta": {"title": title}}), encoding="utf-8")
    (folder / f"{slug}.md").write_text(f"# {title}\n\nBody.", encoding="utf-8")


def setup_client(m, role="reviewer", username="jane@acme.com", pw="correct-horse-1"):
    s = m.store()
    ws = s.create_workspace("Acme Cloud")
    user = s.create_user(username, pw)
    s.set_role(user["id"], ws["id"], role)
    return ws, user


def test_a_client_member_sees_only_their_workspace():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws, _ = setup_client(m)
        article(Path(d), "studio-post", "The studio's own post")
        article(m.ws_dir(ws), "acme-post", "Acme's post")
        c = m.app.test_client()
        c.post("/login", data={"username": "jane@acme.com", "password": "correct-horse-1"})
        body = c.get("/library").data.decode()
        assert "Acme&#39;s post" in body or "Acme's post" in body, body[:400]
        assert "studio&#39;s own post" not in body and "studio's own post" not in body
        # Asking for the default workspace by name does not get them in.
        assert c.get("/workspace/default").status_code == 404
        assert c.get("/output/studio-post.md").status_code == 404
        assert c.get("/output/acme-post.md").status_code == 200


def test_files_outside_the_workspace_folder_are_never_served():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws, _ = setup_client(m)
        article(m.ws_dir(ws), "acme-post", "Acme's post")
        c = m.app.test_client()
        h = basic("admin", "s3cret")
        for path in ("/output/workspaces/acme-cloud/acme-post.md", "/output/_system/humanly.db",
                     "/output/.voice_profile.json"):
            assert c.get(path, headers=h).status_code == 404, path


def test_a_client_reviewer_cannot_spend_credits():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        setup_client(m, role="reviewer")
        h = basic("jane@acme.com", "correct-horse-1")
        c = m.app.test_client()
        assert c.post("/api/start", json={"topic": "x"}, headers=h).status_code == 403
        assert c.post("/api/radar", json={}, headers=h).status_code == 403
        assert c.get("/settings", headers=h).status_code == 403


def test_a_writer_runs_jobs_into_their_own_workspace_folder():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws, _ = setup_client(m, role="writer")
        spawned = {}
        m._spawn = lambda cmd, **kw: (spawned.update(cmd=cmd, **kw), "job-1")[1]
        r = m.app.test_client().post("/api/start", json={"topic": "Kubernetes costs"},
                                     headers=basic("jane@acme.com", "correct-horse-1"))
        assert r.status_code == 200, r.data
        out = spawned["cmd"][spawned["cmd"].index("--output-dir") + 1]
        assert Path(out) == m.ws_dir(ws), out


def test_someone_with_no_workspace_is_told_so():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        m.store().create_user("loner", "correct-horse-1")
        c = m.app.test_client()
        c.post("/login", data={"username": "loner", "password": "correct-horse-1"})
        r = c.get("/")
        assert r.status_code == 403 and b"No workspace yet" in r.data


def test_changing_a_password_signs_out_other_sessions():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        _, user = setup_client(m, role="writer")
        a, b = m.app.test_client(), m.app.test_client()
        for c in (a, b):
            c.post("/login", data={"username": "jane@acme.com", "password": "correct-horse-1"})
            assert c.get("/library").status_code == 200
        r = a.post("/account", data={"current": "correct-horse-1", "new": "battery-staple-2",
                                     "confirm": "battery-staple-2"})
        assert b"Password changed" in r.data
        assert a.get("/library").status_code == 200, "the session that changed it stays in"
        assert b.get("/library").status_code == 302, "every other session is signed out"


def test_a_disabled_account_is_locked_out():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        _, user = setup_client(m)
        c = m.app.test_client()
        c.post("/login", data={"username": "jane@acme.com", "password": "correct-horse-1"})
        m.store().set_disabled(user["id"], True)
        assert c.get("/library").status_code == 302


def test_a_cross_site_post_is_refused():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        c = m.app.test_client()
        c.post("/login", data={"password": "s3cret"})
        r = c.post("/api/radar", json={}, headers={"Origin": "https://evil.example.com"})
        assert r.status_code == 403


def test_the_client_feed_carries_only_approved_work():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws, _ = setup_client(m)
        article(m.ws_dir(ws), "draft-post", "Still a draft")
        article(m.ws_dir(ws), "ok-post", "Signed off")
        m.store().set_status(ws["id"], "ok-post", "approved", "jane")
        feed = m.app.test_client().get(f"/feed.json?ws={ws['slug']}").get_json()
        titles = [i["title"] for i in feed["items"]]
        assert titles == ["Signed off"], titles
        assert feed["author"]["name"] == "Acme Cloud", "a client never inherits the studio's byline"


def test_an_admin_creates_a_client_and_becomes_its_owner():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        c = m.app.test_client()
        c.post("/login", data={"password": "s3cret"})
        r = c.post("/admin", data={"action": "create_workspace", "name": "Globex"})
        assert r.status_code == 302 and "/settings" in r.headers["Location"]
        assert m.store().workspace("globex")["name"] == "Globex"
        page = c.get("/settings").data.decode()
        assert "Globex" in page
        log = c.get("/settings/audit").data.decode()
        assert "workspace.created" in log


def test_owner_adds_a_reviewer_with_a_one_time_password():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        c = m.app.test_client()
        c.post("/login", data={"password": "s3cret"})
        r = c.post("/settings", data={"action": "add_member", "username": "cfo@client.com",
                                      "role": "reviewer"}, follow_redirects=True)
        assert b"Temporary password" in r.data
        user = m.store().user_by_name("cfo@client.com")
        assert m.store().role_in(user, m.store().workspace("default")) == "reviewer"
