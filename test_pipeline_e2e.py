"""run() end to end with every network call faked: the wiring between steps,
the files that come out, and the batch-A behaviours (no dead links, only
real images, no greeting at edition 0, ElevenLabs in the ledger)."""
import json
import os
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402

OUTLINE = "# T\n\n## Intro\n\n## Simple [DIAGRAM: A | Shows: b]\n\n## Deep\n\n## FAQ\n\n## Conclusion"
ARTICLE = """# Semantic caching explained

## Introduction

Caches remember. Read our [GPU guide](#) and the [real one](https://site.test/real-one).

## The simple version

A cache is a box. You put answers in. You take them out.

[DIAGRAM: Cache path | Shows: the cache sits before the model]

## How it works

Detail with a number (Source: https://vendor.test/pricing).

[IMAGE: cache diagram | Query: semantic cache architecture]

[IMAGE: second | Query: llm cache]

## Frequently asked questions

### Is it fast?

Yes.

## Conclusion

Try it.
"""


def fake_claude(prompt, system="", **kw):
    if "Return ONLY valid JSON" in prompt or "Return ONLY JSON" in prompt:
        if '"themes"' in prompt:
            return '{"themes": [], "skipped": []}'
        if '"facts"' in prompt:
            return '{"facts": [], "primary_sources": [], "gaps": []}'
        if '"type": "flow | cycle' in prompt:
            return json.dumps({"type": "flow", "title": "Cache path", "nodes": ["Ask", "Check", "Answer"], "caption": "c"})
        return '{"title": "Semantic caching explained", "description": "d", "slug": "semantic-caching-explained"}'
    if "Create a detailed article outline" in prompt:
        return OUTLINE
    if "Write a complete, high-quality SEO article" in prompt:
        return ARTICLE
    if "Rewrite the article below to remove AI writing patterns" in prompt or "QUESTION 1" in prompt:
        return "REMAINING TELLS:\nNone found\n\nREVISED ARTICLE:\n" + ARTICLE if "QUESTION 1" in prompt else ARTICLE
    if "key takeaways" in prompt.lower():
        return "- t1\n- t2"
    if "refine" in prompt.lower() and "title" in prompt.lower():
        return "Semantic caching explained"
    return ARTICLE


def test_run_end_to_end(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(sw, "SITE_URL", "https://site.test")
    # an earlier article in the library, so an internal link candidate exists
    (tmp_path / "real-one_meta.json").write_text(json.dumps({"seo_meta": {"title": "The real one"}}), encoding="utf-8")

    monkeypatch.setattr(sw, "serp_research", lambda title, keywords, intent="": {
        "keywords": {"primary_keyword": keywords or title, "secondary_keywords": []},
        "semantic_analysis": {}, "serp_context": "(faked)", "writing_tone": "plain",
        "writing_style": "direct", "search_intent": "learn", "target_audience": "engineers",
        "article_goal": "explain", "hidden_insight": "x"})
    monkeypatch.setattr(sw, "load_style_samples", lambda *a, **k: "--- Sample: s ---\nShort. Direct.")
    monkeypatch.setattr(sw, "build_voice_profile", lambda samples: "Short sentences.")
    monkeypatch.setattr(sw, "call_claude", fake_claude)
    monkeypatch.setattr(sw, "call_agent", lambda role, prompt, system="", **kw:
                        '{"verdict":"pass","scores":{"factual_support":9},"issues":[]}')
    monkeypatch.setattr(sw, "resolve_agents", lambda: {
        "writer": {"provider": "anthropic", "model": "m", "effort": "low"},
        "auditor": {"provider": "anthropic", "model": "m", "effort": "low"},
        "judge": {"provider": "anthropic", "model": "m", "effort": "low"}})
    monkeypatch.setattr(sw, "generate_answer_block", lambda *a, **k: "Semantic caching reuses answers.")

    class _R:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p

    def fake_get(url, params=None, **kw):
        assert "serpapi" in url
        return _R({"images_results": [
            {"original": "x-raw-image:///abc", "source": "bad"},
            {"original": "https://media.licdn.com/dms/image/v2/x?e=1&t=tok", "source": "linkedin"},
            {"original": "https://cdn.test/img/cache.png", "source": "https://cdn.test/post"},
        ]})
    monkeypatch.setattr(sw.requests, "get", fake_get)
    monkeypatch.setenv("SERPAPI_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    monkeypatch.setattr(sw.requests, "post", lambda *a, **kw: type("P", (), {
        "status_code": 200, "headers": {"content-type": "audio/mpeg"}, "content": b"ID3" + b"\0" * 2000,
        "raise_for_status": lambda self: None})())
    monkeypatch.setattr(sw, "generate_video_script", lambda *a, **k: "# s\n\n## 1. Hook (0:00-0:10)\n**Visual:** x\n\nSpoken words here, more than twenty of them at least to pass the narration length guard, yes indeed they are, and then some more.\n\n---\n\n## Narration only\n\nSpoken words here, more than twenty of them at least to pass the narration length guard, yes indeed they are, and then some more.\n")
    monkeypatch.setattr(sw, "generate_linkedin_post", lambda *a, **k: "post")

    sw.run("Semantic caching explained", "semantic caching", tmp_path, edition=0,
           intent="explain", take="I think caches are underrated", words="1000",
           linkedin=True, video=True, voiceover=True, facts=False, diagram=True)
    out = capsys.readouterr().out
    slug = "semantic-caching-explained"

    md = (tmp_path / f"{slug}.md").read_text(encoding="utf-8")
    assert "](#)" not in md and "GPU guide" in md                         # dead link stripped, text kept
    assert "https://site.test/real-one" in md                             # real link kept
    assert not md.startswith("👋") and "Welcome to Edition" not in md    # edition 0: no greeting
    assert "![cache diagram](https://cdn.test/img/cache.png)" in md       # the one usable result
    assert "x-raw-image" not in md and "licdn" not in md and "unsplash" not in md
    assert "[IMAGE:" not in md                                            # unusable placements dropped
    assert f"{slug}_diagram_1.png" in md
    assert "Placeholder links removed" in out
    assert md.count("![") >= 3                                             # two searched images + the diagram

    for name in (f"{slug}.html", f"{slug}.docx", f"{slug}_meta.json", f"{slug}_facts.json",
                 f"{slug}_linkedin.md", f"{slug}_video.md", f"{slug}_voiceover.mp3", f"{slug}_usage.json"):
        assert (tmp_path / name).exists(), name
    usage = json.loads((tmp_path / f"{slug}_usage.json").read_text(encoding="utf-8"))
    assert "elevenlabs-tts" in json.dumps(usage)                          # narration in the ledger
    assert (tmp_path / ".voice_profile.json").exists() is False           # faked builder writes nothing
    assert sw.VOICE_PROFILE_PATH == tmp_path / ".voice_profile.json"      # but the cache would land here


def test_library_links_need_a_site(tmp_path: Path, monkeypatch):
    (tmp_path / "a_meta.json").write_text(json.dumps({"seo_meta": {"title": "A"}}), encoding="utf-8")
    monkeypatch.setattr(sw, "SITE_URL", "")
    assert sw.library_links(tmp_path) == []
    assert "Plan no internal links" in sw.internal_links_block([])
    monkeypatch.setattr(sw, "SITE_URL", "https://s.test")
    links = sw.library_links(tmp_path, exclude_title="a")
    assert links == []                                                    # excludes itself, case-insensitively
    assert sw.library_links(tmp_path) == [{"title": "A", "url": "https://s.test/a"}]
    assert "https://s.test/a" in sw.internal_links_block(sw.library_links(tmp_path))


def test_usable_image_url():
    ok = sw.usable_image_url
    assert ok("https://cdn.test/a/b.png") and ok("https://x.test/images/photo")
    assert not ok("x-raw-image:///abc") and not ok("http://insecure.test/a.png")
    assert not ok("https://media.licdn.com/dms/image/v2/x?e=1&t=tok")
    assert not ok("https://unsplash.com/s/photos/query") and not ok("")


def test_strip_placeholder_links():
    assert sw.strip_placeholder_links("See [this](#) and [that](#anchor) and [keep](https://k.test).") == \
        "See this and that and [keep](https://k.test)."
