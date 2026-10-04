"""Tests for site intake: finding a client's pages, reading them, refusing
private addresses, and what the app does with the result."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import site_intake as si  # noqa: E402


def test_pages_are_sorted_into_articles_products_and_the_rest():
    assert si.classify("https://acme.example/blog/cutting-k8s-costs/") == "article"
    assert si.classify("https://acme.example/2024/05/a-post/") == "article"
    assert si.classify("https://acme.example/blog/") == "other", "the listing is not an article"
    assert si.classify("https://acme.example/pricing") == "product"
    assert si.classify("https://acme.example/solutions/finops/") == "product"
    assert si.classify("https://acme.example/tag/kubernetes/") == "skip"
    assert si.classify("https://acme.example/about") == "other"


def test_the_readable_body_leaves_navigation_and_scripts_out():
    html = """<html><head><title>Cutting costs | Acme</title></head><body>
      <nav><p>Home Products Pricing Blog Contact us today please</p></nav>
      <article><h1>Cutting costs</h1><p>Most clusters run at a third of what they pay for, which is the first thing to fix.</p>
      <ul><li>Right-size requests</li></ul></article>
      <script>var tracking = "nope";</script>
      <footer><p>Copyright Acme, all rights reserved, every single one of them</p></footer></body></html>"""
    p = si._Text()
    p.feed(html)
    text = "\n".join(p.out)
    assert "# Cutting costs" in text and "Right-size requests" in text
    assert "tracking" not in text and "Copyright" not in text and "Contact us" not in text


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/",
                                 "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd"])
def test_private_and_local_addresses_are_refused(url):
    with pytest.raises(si.BlockedURL):
        si._check_public(url)


class _Resp:
    def __init__(self, text, status=200, ctype="text/html; charset=utf-8"):
        self.text, self.content, self.status_code = text, text.encode(), status
        self.ok = status < 400
        self.headers = {"Content-Type": ctype}
        self.is_redirect = False


def _article(title, words):
    body = " ".join(["Kubernetes cost work is mostly about requests and limits."] * (words // 9))
    return f"<html><head><title>{title} | Acme</title></head><body><article><h1>{title}</h1><p>{body}</p></article></body></html>"


SITE = {
    "https://acme.example/robots.txt": _Resp("User-agent: *\nDisallow: /private/\nSitemap: https://acme.example/sitemap.xml", ctype="text/plain"),
    "https://acme.example/sitemap.xml": _Resp("""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://acme.example/blog/rightsizing/</loc><lastmod>2026-09-01</lastmod></url>
        <url><loc>https://acme.example/blog/spot-nodes/</loc><lastmod>2026-08-01</lastmod></url>
        <url><loc>https://acme.example/pricing</loc></url>
        <url><loc>https://acme.example/private/secret/</loc></url>
        <url><loc>https://other.example/blog/not-ours/</loc></url>
        </urlset>""", ctype="application/xml"),
    "https://acme.example/blog/rightsizing/": _Resp(_article("Rightsizing pods", 900)),
    "https://acme.example/blog/spot-nodes/": _Resp(_article("Spot nodes", 700)),
    "https://acme.example/pricing": _Resp(_article("Pricing", 300)),
}


def test_a_full_intake_writes_pages_samples_and_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "_check_public", lambda url: None)
    fetched = []

    def fake_get(self, url, check_robots=True):
        if check_robots and not self.allowed(url):
            return None
        fetched.append(url)
        return SITE.get(url, _Resp("", status=404))

    monkeypatch.setattr(si.Fetcher, "get", fake_get)
    summary = si.run("acme.example", tmp_path)
    pages = json.loads((tmp_path / "site_pages.json").read_text(encoding="utf-8"))
    urls = {p["url"] for p in pages}
    assert "https://other.example/blog/not-ours/" not in urls, "another site's pages are not theirs"
    assert summary["article"] == 2 and summary["product"] == 1
    assert "https://acme.example/private/secret/" not in fetched, "robots.txt is honoured"
    samples = sorted(p.name for p in (tmp_path / "samples").glob("*.md"))
    assert samples == ["site-blog-rightsizing.md", "site-blog-spot-nodes.md"], samples
    note = (tmp_path / "notes" / "site-pricing.md").read_text(encoding="utf-8")
    assert "Source: https://acme.example/pricing" in note, "every note carries its URL"
    titles = {p["title"] for p in pages}
    assert "Rightsizing pods" in titles, titles


# --- the app ------------------------------------------------------------------

def make_app(tmp):
    os.environ["APP_PASSWORD"] = ""
    sys.modules.pop("app", None)
    import app as m
    m.OUTPUT_DIR = Path(tmp)
    m.APP_PASSWORD = ""
    m.app.config["TESTING"] = True
    m._start_workers = lambda: None
    return m


def test_settings_starts_an_intake_job_into_the_workspace_folder():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = m.store().create_workspace("Acme Cloud")
        c = m.app.test_client()
        c.get(f"/workspace/{ws['slug']}")
        spawned = {}
        m._spawn = lambda cmd, **kw: (spawned.update(cmd=cmd, **kw), "job-9")[1]
        r = c.post("/settings", data={"action": "intake", "url": "acme.example"})
        assert r.status_code == 302
        assert spawned["kind"] == "intake"
        assert spawned["cmd"][2] == "https://acme.example"
        assert Path(spawned["cmd"][spawned["cmd"].index("--out") + 1]) == m.ws_dir(m.store().workspace(ws["slug"]))
        assert m.store().workspace(ws["slug"])["settings"]["site_url"] == "https://acme.example"


def test_a_topic_they_already_cover_is_flagged():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = m.store().create_workspace("Acme Cloud")
        folder = m.ws_dir(ws)
        folder.mkdir(parents=True)
        (folder / "site_pages.json").write_text(json.dumps([
            {"url": "https://acme.example/blog/rightsizing", "title": "Rightsizing Kubernetes pods to cut cost", "kind": "article"},
            {"url": "https://acme.example/careers", "title": "Careers", "kind": "other"}]), encoding="utf-8")
        c = m.app.test_client()
        c.get(f"/workspace/{ws['slug']}")
        hits = c.get("/api/site/overlap?topic=How to rightsize Kubernetes pods and cut cost").get_json()["matches"]
        assert hits and hits[0]["url"].endswith("/rightsizing"), hits
        assert c.get("/api/site/overlap?topic=Postgres vacuum tuning explained").get_json()["matches"] == []


def test_a_client_article_uses_their_product_notes_unless_switched_off():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        ws = m.store().create_workspace("Acme Cloud")
        notes = m.ws_dir(ws) / "notes"
        notes.mkdir(parents=True)
        (notes / "site-pricing.md").write_text("# Pricing\n\nSource: https://acme.example/pricing\n", encoding="utf-8")
        c = m.app.test_client()
        c.get(f"/workspace/{ws['slug']}")
        spawned = {}
        m._spawn = lambda cmd, **kw: (spawned.update(cmd=cmd), "job-1")[1]
        c.post("/api/start", json={"topic": "Cutting cost"})
        assert spawned["cmd"][spawned["cmd"].index("--notes") + 1] == str(notes)
        c.post("/api/start", json={"topic": "Cutting cost", "use_site_notes": False})
        assert "--notes" not in spawned["cmd"]
