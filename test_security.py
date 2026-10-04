"""Tests for retention, security headers, the trust page, and refusal fallback."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import seo_writer as sw  # noqa: E402


def make_app(tmp):
    os.environ["APP_PASSWORD"] = ""
    sys.modules.pop("app", None)
    import app as m
    m.OUTPUT_DIR = Path(tmp)
    m.APP_PASSWORD = ""
    m.app.config["TESTING"] = True
    m._start_workers = lambda: None
    return m


def test_retention_deletes_old_articles_whole_and_nothing_else():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        s = m.store()
        ws = s.create_workspace("Acme", {"retention_days": "30"})
        keep = s.create_workspace("Keeps everything")
        out, other = m.ws_dir(ws), m.ws_dir(keep)
        for folder in (out, other):
            folder.mkdir(parents=True)
        old = time.time() - 40 * 86400
        for name in ("old.md", "old_meta.json", "old_diagram_1.png", "old-but-different_meta.json",
                     "new.md", "new_meta.json"):
            (out / name).write_text("x", encoding="utf-8")
        (other / "ancient_meta.json").write_text("x", encoding="utf-8")
        for f in ("old.md", "old_meta.json", "old_diagram_1.png"):
            os.utime(out / f, (old, old))
        os.utime(other / "ancient_meta.json", (old, old))
        (out / m.VERSIONS).mkdir()
        (out / m.VERSIONS / "old.2026-01-01_000000.md").write_text("x", encoding="utf-8")
        s.set_status(ws["id"], "old", "approved", "t")
        s.add_comment(ws["id"], "old", "t", "looks good")

        assert m.sweep_retention() == {ws["slug"]: 1}
        left = sorted(p.name for p in out.iterdir() if p.is_file())
        assert left == ["new.md", "new_meta.json", "old-but-different_meta.json"], left
        assert not list((out / m.VERSIONS).iterdir()), "versions go too"
        assert s.comments(ws["id"], "old") == [] and s.article_state(ws["id"], "old")["status"] == "draft"
        assert (other / "ancient_meta.json").exists(), "a workspace with no retention keeps everything"
        assert any(r["action"] == "retention.deleted" for r in s.audit_log(ws["id"]))


def test_responses_carry_security_headers():
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        r = m.app.test_client().get("/healthz")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_the_trust_page_is_public_and_lists_only_services_in_use(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        m = make_app(d)
        m.APP_PASSWORD = "s3cret"
        monkeypatch.setenv("SERPAPI_KEY", "x")
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        r = m.app.test_client().get("/trust")
        assert r.status_code == 200, "readable before signing in"
        page = r.data.decode()
        assert "SerpAPI" in page and "ElevenLabs" not in page


class _FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kw):
        self.kwargs = kw
        return self.response


def _response(stop_reason="end_turn", text="OK", category=None, model="claude-sonnet-5-5"):
    return SimpleNamespace(
        stop_reason=stop_reason, model=model,
        stop_details=SimpleNamespace(category=category) if category else None,
        content=[SimpleNamespace(type="text", text=text)] if text else [],
        usage=SimpleNamespace(input_tokens=10, output_tokens=2, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0))


def test_requests_opt_into_server_side_fallback(monkeypatch):
    fake = _FakeMessages(_response(model="claude-sonnet-5"))
    monkeypatch.setattr(sw, "client", SimpleNamespace(beta=SimpleNamespace(messages=fake), messages=fake))
    monkeypatch.setattr(sw, "USE_FALLBACKS", True)
    sw.reset_usage()
    assert sw.call_claude("hi") == "OK"
    assert fake.kwargs["fallbacks"] == "default"
    assert fake.kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert "claude-sonnet-5" in sw.usage_summary()["by_model"], "priced as the model that answered"


def test_a_refusal_says_which_kind(monkeypatch):
    fake = _FakeMessages(_response(stop_reason="refusal", text="", category="frontier_llm"))
    monkeypatch.setattr(sw, "client", SimpleNamespace(beta=SimpleNamespace(messages=fake), messages=fake))
    try:
        sw.call_claude("hi")
    except sw.ClaudeError as e:
        assert "frontier_llm" in str(e) and "rephrase" in str(e)
    else:
        raise AssertionError("a refusal must not come back as text")


def test_fallbacks_can_be_switched_off(monkeypatch):
    fake = _FakeMessages(_response())
    monkeypatch.setattr(sw, "client", SimpleNamespace(beta=SimpleNamespace(messages=fake), messages=fake))
    monkeypatch.setattr(sw, "USE_FALLBACKS", False)
    sw.call_claude("hi")
    assert "fallbacks" not in fake.kwargs and "betas" not in fake.kwargs
