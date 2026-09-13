"""Tests for the finished video: beats, captions from timings, slides, and a
real ffmpeg render with the narration faked."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402

SCRIPT = """# Semantic caching - video script

**Runtime:** 0:30  **Narration:** 40 words

## 1. Hook (0:00-0:10)
**Visual:** Text on screen: "Same question. Twice." Counter climbing.

Most RAG apps answer the **same question** twice. Every time.

## 2. The core idea (0:10-0:20)
**Visual:** Simple diagram building: cache between app and model.

A semantic cache matches [meaning](https://x.test), not text. Rephrased questions hit.

## 3. Close (0:20-0:30)
**Visual:** The article title on screen.

Read the full article for the numbers.

---

## Narration only

Most RAG apps answer the same question twice. Every time.
"""


def test_video_beats_parse_labels_and_clean_narration():
    beats = sw.video_beats(SCRIPT)
    assert [b["label"] for b in beats] == ["Hook", "The core idea", "Close"]
    assert beats[0]["narration"] == "Most RAG apps answer the same question twice. Every time."
    assert beats[1]["narration"] == "A semantic cache matches meaning, not text. Rephrased questions hit."
    assert beats[1]["visual"].startswith("Simple diagram")


def test_slide_headline_prefers_on_screen_text():
    beats = sw.video_beats(SCRIPT)
    assert sw.slide_headline(beats[0]) == "Same question. Twice."
    assert sw.slide_headline(beats[1]) == "A semantic cache matches meaning, not text."


def _timed(text: str, cps: float = 15.0):
    """Fake alignment: every character takes 1/cps seconds."""
    return [(ch, i / cps, (i + 1) / cps) for i, ch in enumerate(text)]


def test_caption_cues_break_on_sentences_and_length():
    chars = _timed("Most RAG apps answer the same question twice. Every time. " + "word " * 20)
    cues = sw.caption_cues(chars, max_chars=42)
    assert cues[0][2] == "Most RAG apps answer the same question twice."
    assert cues[1][2] == "Every time."
    assert all(len(t) <= 50 for _, _, t in cues)
    assert cues[0][0] == 0.0 and cues[0][1] <= cues[1][0]           # no overlap
    for s, e, _ in cues:
        assert e > s


def test_srt_format(tmp_path: Path):
    p = tmp_path / "c.srt"
    sw.write_srt([(0.0, 1.25, "Hello."), (61.5, 62.0, "Bye.")], p)
    text = p.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,250\nHello.\n" in text
    assert "2\n00:01:01,500 --> 00:01:02,000\nBye.\n" in text


@pytest.mark.parametrize("fmt", ["16x9", "9x16"])
def test_render_slide_sizes_and_diagram(tmp_path: Path, fmt):
    from PIL import Image
    diagram = tmp_path / "d.png"
    Image.new("RGB", (1200, 400), "white").save(diagram)
    beats = sw.video_beats(SCRIPT)
    size = sw.VIDEO_FORMATS[fmt]
    for n, b in enumerate(beats, 1):
        out = tmp_path / f"s{fmt}{n}.png"
        sw.render_slide(b, n, len(beats), size, out, diagram=diagram, brand="Humanly")
        im = Image.open(out)
        assert im.size == size
        assert len(im.getcolors(maxcolors=200000) or []) > 10
    # beat 2 asks for the diagram: a white panel appears
    im2 = Image.open(tmp_path / f"s{fmt}2.png").convert("RGB")
    assert (255, 255, 255) in {c for _, c in (im2.getcolors(maxcolors=200000) or [])}


def test_make_video_skips_without_keys_or_ffmpeg(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert sw.make_video(SCRIPT, "slug", tmp_path) == {}
    assert "Skipped" in capsys.readouterr().out
    monkeypatch.setattr(sw, "_ffmpeg", lambda: None)
    assert sw.make_video(SCRIPT, "slug", tmp_path, tts=lambda t: (b"", [])) == {}
    assert "ffmpeg" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_make_video_renders_both_formats_with_fake_narration(tmp_path: Path):
    """Real ffmpeg; the narration is a generated tone with fake timings."""
    def fake_tts(text):
        secs = max(1.0, len(text) / 15.0)
        mp3 = tmp_path / "tone.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=440:duration={secs}", "-q:a", "6", str(mp3)], check=True)
        return mp3.read_bytes(), _timed(text)

    out = sw.make_video(SCRIPT, "slug", tmp_path, tts=fake_tts)
    assert out["beats"] == 3 and out["duration"] > 5
    for fmt in ("16x9", "9x16"):
        mp4 = tmp_path / out[f"video_{fmt}"]
        assert mp4.exists() and mp4.stat().st_size > 20_000
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height", "-of", "csv=p=0", str(mp4)],
                               capture_output=True, text=True).stdout.strip()
        assert probe == f"{sw.VIDEO_FORMATS[fmt][0]},{sw.VIDEO_FORMATS[fmt][1]}"
    assert (tmp_path / "slug_voiceover.mp3").exists()
    srt = (tmp_path / "slug_captions.srt").read_text(encoding="utf-8")
    assert "Most RAG apps answer the same question twice." in srt
    assert "Read the full article for the numbers." in srt


def test_video_meta_prompt_carries_chapters(monkeypatch):
    seen = {}
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: (seen.update(p=prompt), "# Video text")[1])
    beats = sw.video_beats(SCRIPT)
    beats[0]["duration"], beats[1]["duration"], beats[2]["duration"] = 12.4, 30.0, 8.0
    sw.generate_video_meta("T", SCRIPT, "article", {"keywords": {}, "voice_profile": "Short."}, beats=beats)
    assert "0:00 Hook" in seen["p"] and "0:12 The core idea" in seen["p"] and "0:42 Close" in seen["p"]
    assert "Short." in seen["p"]


def test_app_passes_the_mp4_flag(tmp_path: Path, monkeypatch):
    os.environ["APP_PASSWORD"] = ""
    import app as a
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    spawned = {}
    monkeypatch.setattr(a, "_spawn", lambda cmd, **kw: (spawned.update(cmd=cmd), "job-3")[1])
    c = a.app.test_client()
    c.post("/api/start", json={"topic": "t", "mp4": True})
    assert "--mp4" in spawned["cmd"]
    html = c.get("/").get_data(as_text=True)
    assert 'id="mp4"' in html and "Finished video" in html
    for name in ("slug_meta.json",):
        (tmp_path / name).write_text('{"seo_meta": {"title": "S"}}', encoding="utf-8")
    (tmp_path / "slug.md").write_text("w", encoding="utf-8")
    (tmp_path / "slug_video_16x9.mp4").write_bytes(b"0")
    (tmp_path / "slug_video_meta.md").write_text("m", encoding="utf-8")
    art = a.list_articles()[0]
    assert art["mp4_wide"] == "slug_video_16x9.mp4" and art["mp4_tall"] is None and art["video_meta"] == "slug_video_meta.md"
    assert "Video 16:9" in c.get("/library").get_data(as_text=True)
