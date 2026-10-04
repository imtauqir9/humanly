"""Tests for the approval workflow: draft, review, changes, approval, and what
an edit after sign-off does."""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

BODY = "# Cutting Kubernetes costs\n\n" + ("Requests and limits decide most of the bill. " * 20) + "\n"


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


def world(m, require_approval=True):
    """A client workspace with a writer, a client reviewer, an editor and one draft."""
    s = m.store()
    ws = s.create_workspace("Acme Cloud", {"require_approval": require_approval})
    for name, role in (("writer", "writer"), ("client", "reviewer"), ("editor", "editor")):
        u = s.create_user(name, "correct-horse-1")
        s.set_role(u["id"], ws["id"], role)
    folder = m.ws_dir(ws)
    folder.mkdir(parents=True)
    (folder / "k8s-costs.md").write_text(BODY, encoding="utf-8")
    (folder / "k8s-costs_meta.json").write_text(json.dumps({"seo_meta": {"title": "Cutting Kubernetes costs"}}),
                                               encoding="utf-8")
    s.set_status(ws["id"], "k8s-costs", "draft", "writer")
    return ws


def move(c, who, status, note=""):
    return c.post("/a/k8s-costs/status", data={"status": status, "note": note}, headers=h(who))


def test_the_path_from_draft_to_approved():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = world(m)
        c = m.app.test_client()
        assert move(c, "client", "approved").status_code == 403, "nothing to approve yet"
        assert move(c, "writer", "in_review").status_code == 302
        assert move(c, "writer", "approved").status_code == 403, "a writer cannot approve their own work"
        assert move(c, "client", "changes", "Shorter intro, please").status_code == 302
        assert m.store().article_state(ws["id"], "k8s-costs")["status"] == "changes"
        assert move(c, "writer", "in_review").status_code == 302
        assert move(c, "client", "approved").status_code == 302
        assert m.store().article_state(ws["id"], "k8s-costs")["status"] == "approved"
        thread = [x["body"] for x in m.store().comments(ws["id"], "k8s-costs")]
        assert any("Shorter intro, please" in b for b in thread), thread
        assert any("In review → Approved" in b for b in thread), thread
        log = [r["action"] for r in m.store().audit_log(ws["id"])]
        assert log.count("article.status") == 4, "one entry per move that happened"


def test_a_client_reviewer_comments_but_cannot_edit():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = world(m)
        c = m.app.test_client()
        r = c.post("/a/k8s-costs/comment", data={"body": "Can we mention the FinOps report?"}, headers=h("client"))
        assert r.status_code == 302
        assert m.store().comments(ws["id"], "k8s-costs")[0]["username"] == "client"
        r = c.post("/a/k8s-costs/edit", data={"markdown": BODY + "extra"}, headers=h("client"))
        assert r.status_code == 403


def test_the_article_page_shows_only_the_moves_you_may_make():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        world(m)
        c = m.app.test_client()
        page = c.get("/a/k8s-costs", headers=h("writer")).data.decode()
        assert "Send for review" in page and "Approve" not in page
        move(c, "writer", "in_review")
        page = c.get("/a/k8s-costs", headers=h("client")).data.decode()
        assert "Approve" in page and "Request changes" in page and "Edit text" not in page


def test_an_edit_after_approval_needs_approving_again_and_keeps_the_old_text():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = world(m)
        c = m.app.test_client()
        move(c, "writer", "in_review")
        move(c, "client", "approved")
        new = BODY.replace("most of the bill", "nearly all of the bill")
        r = c.post("/a/k8s-costs/edit", data={"markdown": new}, headers=h("editor"))
        assert r.status_code == 302 and "msg=" in r.headers["Location"], r.headers["Location"]
        folder = m.ws_dir(ws)
        assert "nearly all of the bill" in (folder / "k8s-costs.md").read_text(encoding="utf-8")
        assert m.store().article_state(ws["id"], "k8s-costs")["status"] == "in_review"
        versions = list((folder / "_versions").glob("k8s-costs.*.md"))
        assert len(versions) == 1 and "most of the bill" in versions[0].read_text(encoding="utf-8")
        html = (folder / "k8s-costs.html").read_text(encoding="utf-8")
        assert "nearly all of the bill" in html, "the HTML is rebuilt from the edit"
        assert "Imran" not in html, "rebuilt as the client, not the studio"
        # And restoring brings the old text back, keeping the edited one as a version too.
        r = c.post("/a/k8s-costs/restore", data={"name": versions[0].name}, headers=h("editor"))
        assert "most of the bill" in (folder / "k8s-costs.md").read_text(encoding="utf-8")
        assert len(list((folder / "_versions").glob("k8s-costs.*.md"))) >= 1


def test_without_approval_required_an_edit_leaves_the_status_alone():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = world(m, require_approval=False)
        m._rerender = lambda slug: ""
        c = m.app.test_client()
        move(c, "writer", "in_review")
        move(c, "editor", "approved")
        c.post("/a/k8s-costs/edit", data={"markdown": BODY + "\nOne more line of text here."}, headers=h("editor"))
        assert m.store().article_state(ws["id"], "k8s-costs")["status"] == "approved"


def test_an_unknown_article_is_a_404():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        world(m)
        c = m.app.test_client()
        assert c.get("/a/nope", headers=h("writer")).status_code == 404
        assert c.get("/a/..%2F..%2Fsecrets", headers=h("writer")).status_code == 404
