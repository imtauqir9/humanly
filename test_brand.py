"""Tests for writing as a client: their URLs, their brand rules, their pages,
and none of the studio owner's own byline, greeting or sign-off."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import seo_writer as sw  # noqa: E402

HERE = Path(__file__).parent


def test_the_url_pattern_shapes_canonical_links(monkeypatch):
    monkeypatch.setattr(sw, "SITE_URL", "https://acme.example")
    monkeypatch.setattr(sw, "ARTICLE_URL_PATTERN", "{site}/blog/{slug}")
    assert sw.public_url("k8s-costs") == "https://acme.example/blog/k8s-costs"
    monkeypatch.setattr(sw, "SITE_URL", "")
    assert sw.public_url("k8s-costs") == "", "no site, no guessed URL"


def test_brand_rules_reach_the_writer_and_the_auditor(monkeypatch):
    monkeypatch.setattr(sw, "BRAND_GUIDE", "Never name competitors.")
    assert "Never name competitors." in sw.style_block("", "")
    monkeypatch.setattr(sw, "BRAND_GUIDE", "")
    assert "BRAND GUIDE" not in sw.style_block("", "")


def test_site_pages_are_ranked_by_the_topic(tmp_path, monkeypatch):
    pages = [
        {"url": "https://acme.example/pricing", "title": "Acme pricing"},
        {"url": "https://acme.example/kubernetes-cost-monitoring", "title": "Kubernetes cost monitoring"},
        {"url": "https://acme.example/careers", "title": "Careers at Acme"},
    ]
    f = tmp_path / "site_pages.json"
    f.write_text(json.dumps(pages), encoding="utf-8")
    monkeypatch.setattr(sw, "SITE_PAGES_FILE", str(f))
    got = sw.site_pages("How to cut Kubernetes costs")
    assert got and got[0]["url"].endswith("kubernetes-cost-monitoring"), got
    assert all("careers" not in p["url"] for p in got)


def test_only_live_articles_are_linked_in_a_client_workspace(tmp_path, monkeypatch):
    for slug in ("live-post", "draft-post"):
        (tmp_path / f"{slug}_meta.json").write_text(json.dumps({"seo_meta": {"title": slug}}), encoding="utf-8")
    live = tmp_path / "_published.json"
    live.write_text(json.dumps({"live-post": "https://acme.example/blog/live-post"}), encoding="utf-8")
    monkeypatch.setattr(sw, "SITE_URL", "https://acme.example")
    monkeypatch.setattr(sw, "SITE_PAGES_FILE", "")
    monkeypatch.setattr(sw, "PUBLISHED_FILE", str(live))
    urls = [l["url"] for l in sw.library_links(tmp_path, exclude_title="something else")]
    assert urls == ["https://acme.example/blog/live-post"], urls


def _constants_with(env: dict) -> dict:
    code = ("import json, seo_writer as sw; print(json.dumps({'cta': sw.AUTHOR_CTA, "
            "'intro': sw.AUTHOR_INTRO_TEMPLATE, 'bio': sw.AUTHOR_BIO, 'samples': str(sw.SAMPLE_DIR)}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True,
                         env={**os.environ, "ANTHROPIC_API_KEY": "x", **env}, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_client_workspace_carries_none_of_the_studio_owner():
    got = _constants_with({"BRAND_CTA": "", "BRAND_INTRO": "", "AUTHOR_BIO": "Acme's platform team.",
                           "STYLE_SAMPLES_DIR": "/nowhere/samples"})
    assert got["cta"] == "" and got["intro"] == ""
    assert "Imran" not in got["bio"]
    assert got["samples"].replace("\\", "/").endswith("/nowhere/samples")


def test_a_client_sign_off_replaces_the_studio_one():
    got = _constants_with({"BRAND_CTA": "[Book a demo](https://acme.example/demo)"})
    assert "Book a demo" in got["cta"] and "Imran" not in got["cta"]


def test_the_studio_keeps_its_own_greeting_and_sign_off_by_default():
    env = {k: v for k, v in os.environ.items() if k not in ("BRAND_CTA", "BRAND_INTRO", "AUTHOR_BIO")}
    code = "import seo_writer as sw; print('Imran' in sw.AUTHOR_CTA, 'Imran' in sw.AUTHOR_BIO)"
    out = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True,
                         env={**env, "ANTHROPIC_API_KEY": "x"}, timeout=60)
    assert out.stdout.strip().splitlines()[-1] == "True True", out.stdout + out.stderr


def test_the_app_hands_a_client_workspace_its_own_environment():
    os.environ["APP_PASSWORD"] = ""
    sys.modules.pop("app", None)
    import app as m
    with tempfile.TemporaryDirectory() as d:
        m.OUTPUT_DIR = Path(d)
        m.APP_PASSWORD = ""
        s = m.store()
        ws = s.create_workspace("Acme Cloud", {"site_url": "https://acme.example",
                                               "url_pattern": "{site}/blog/{slug}",
                                               "brand_guide": "Say Acme Cloud.",
                                               "brand_cta": ""})
        s.set_status(ws["id"], "old-post", "published", "t")
        env = m.pipeline_env(ws)
        assert env["AUTHOR_NAME"] == "Acme Cloud"
        assert env["BRAND_CTA"] == "" and env["BRAND_INTRO"] == ""
        assert env["BRAND_GUIDE"] == "Say Acme Cloud."
        assert env["STYLE_SAMPLES_DIR"].endswith(str(Path("acme-cloud") / "samples"))
        assert "Imran" not in json.dumps(env)
        live = json.loads(Path(env["PUBLISHED_FILE"]).read_text(encoding="utf-8"))
        assert live == {"old-post": "https://acme.example/blog/old-post"}
        # The studio's own workspace overrides nothing it has not filled in.
        assert set(m.pipeline_env(s.workspace("default"))) == {"WEB_CALL_DEBUG_DIR", "DL_ROOT"}
