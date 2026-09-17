"""Tests for the voiceover step: what gets spoken, and how the ElevenLabs call
succeeds, fails, and is skipped."""
import os
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402

SCRIPT = """# Semantic caching - video script

**Runtime:** 2:40  **Narration:** 400 words

## 1. Hook (0:00-0:15)
**Visual:** A request counter climbing.

Most RAG apps answer the **same question** twice. Every time.

## 2. The core idea (0:15-0:45)
**Visual:** Two queries, one embedding space.

A semantic cache matches [meaning](https://example.com), not text.

---

## Narration only

Most RAG apps answer the **same question** twice. Every time.

A semantic cache matches [meaning](https://example.com), not text.
"""


def test_narration_prefers_the_narration_block_and_strips_markup():
    text = sw.narration_text(SCRIPT)
    assert text.startswith("Most RAG apps answer the same question twice.")
    assert "**" not in text and "](" not in text and "meaning, not text." in text
    assert "Visual:" not in text and "Runtime" not in text and "#" not in text


def test_narration_falls_back_to_the_beats_when_no_block():
    no_block = SCRIPT.split("---")[0]
    text = sw.narration_text(no_block)
    assert "Most RAG apps answer the same question twice." in text
    assert "A semantic cache matches meaning, not text." in text
    assert "Visual:" not in text and "Runtime" not in text and "## 1." not in text


def test_voiceover_is_skipped_without_keys(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    assert sw.generate_voiceover(SCRIPT, "slug", tmp_path) is None
    assert "Skipped" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


class _Resp:
    def __init__(self, status=200, content=b"", ctype="audio/mpeg", text=""):
        self.status_code, self.content, self.text = status, content, text
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            err = sw.requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


def test_voiceover_posts_the_narration_and_saves_the_mp3(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v123")
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, json=json)
        return _Resp(content=b"ID3" + b"\x00" * 5000)

    monkeypatch.setattr(sw.requests, "post", fake_post)
    long_script = SCRIPT.replace("## Narration only", "## Narration only\n\n" + "Spoken words here. " * 20)
    path = sw.generate_voiceover(long_script, "slug", tmp_path)
    assert path == tmp_path / "slug_voiceover.mp3" and path.stat().st_size > 5000
    assert seen["url"].endswith("/text-to-speech/v123")
    assert seen["headers"]["xi-api-key"] == "k"
    assert seen["json"]["text"] == sw.narration_text(long_script)
    assert "**" not in seen["json"]["text"]


def test_voiceover_reports_api_failure_and_writes_nothing(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v123")
    monkeypatch.setattr(sw.requests, "post",
                        lambda *a, **kw: _Resp(status=401, ctype="application/json", text='{"detail":"bad key"}'))
    long_script = SCRIPT.replace("## Narration only", "## Narration only\n\n" + "Spoken words here. " * 20)
    assert sw.generate_voiceover(long_script, "slug", tmp_path) is None
    out = capsys.readouterr().out
    assert "failed" in out and "bad key" in out
    assert not (tmp_path / "slug_voiceover.mp3").exists()


def test_voiceover_skips_a_script_with_no_narration(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v123")
    monkeypatch.setattr(sw.requests, "post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not call")))
    assert sw.generate_voiceover("# Title\n\n**Visual:** x\n", "slug", tmp_path) is None
