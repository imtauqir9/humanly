"""The radar remembers: decisions on disk, in the prompt, in the filter, in
the app, and an article marks its theme written."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
import seo_writer as sw  # noqa: E402


def test_decisions_round_trip_and_similarity(tmp_path: Path):
    assert sw.load_decisions(tmp_path) == {}
    rec = sw.record_decision(tmp_path, "Agents are lying, colluding, and getting exploited", "skipped", note="tired of it")
    assert rec["status"] == "skipped" and rec["note"] == "tired of it"
    sw.record_decision(tmp_path, "Coding agents' hidden failure modes", "written", slug="coding-agents")
    d = sw.load_decisions(tmp_path)
    assert len(d) == 2 and d["coding agents hidden failure modes"]["slug"] == "coding-agents"
    # exact, near-duplicate, and unrelated
    assert sw.decision_for("agents are lying, colluding and getting exploited", d)["status"] == "skipped"
    assert sw.decision_for("Hidden failure modes of coding agents", d)["status"] == "written"
    assert sw.decision_for("Nvidia and the AI infrastructure bottleneck", d) is None
    with pytest.raises(ValueError):
        sw.record_decision(tmp_path, "x", "maybe")


def test_decisions_block_lists_by_status():
    d = {"a": {"title": "A theme", "status": "written"}, "b": {"title": "B theme", "status": "skipped"},
         "c": {"title": "C theme", "status": "approved"}}
    block = sw.decisions_block(d)
    assert "Already written" in block and "- A theme" in block
    assert "Skipped by the author" in block and "- B theme" in block
    assert "Approved and queued" in block and "- C theme" in block
    assert sw.decisions_block({}) == ""


SIGNALS = [
    {"source": "HN", "kind": "forum", "title": "s1", "url": "https://a.test/1", "discussion": "", "signal": 1, "comments": 0, "date": "", "gist": ""},
    {"source": "HN", "kind": "forum", "title": "s2", "url": "https://a.test/2", "discussion": "", "signal": 1, "comments": 0, "date": "", "gist": ""},
]
EV = [{"url": "https://a.test/1"}, {"url": "https://a.test/2"}]


def test_clean_radar_drops_skipped_and_written_but_keeps_approved(capsys):
    d = {sw._decision_key("Agents colluding in the wild"): {"title": "Agents colluding in the wild", "status": "skipped"},
         sw._decision_key("The GPT-6 release"): {"title": "The GPT-6 release", "status": "written"},
         sw._decision_key("Evals for agents"): {"title": "Evals for agents", "status": "approved"}}
    raw = {"themes": [
        {"title": "Agents colluding in the wild", "score": 90, "evidence": EV},
        {"title": "GPT-6 release arms race", "score": 80, "evidence": EV},
        {"title": "Evals for agents", "score": 70, "evidence": EV},
        {"title": "Something new entirely", "score": 60, "evidence": EV},
    ]}
    out = sw._clean_radar(raw, SIGNALS, d)
    titles = [t["title"] for t in out["themes"]]
    assert titles == ["Evals for agents", "Something new entirely"]
    assert out["themes"][0]["decision"] == "approved" and out["themes"][1]["decision"] is None
    printed = capsys.readouterr().out
    assert "Dropped (skipped earlier): Agents colluding" in printed and "Dropped (written earlier)" in printed


def test_synthesis_prompt_carries_decisions(monkeypatch):
    seen = {}
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: (seen.update(p=prompt), '{"themes": [], "skipped": []}')[1])
    sw.synthesize_radar(SIGNALS, 14, {"k": {"title": "Old theme", "status": "written"}})
    assert "THE AUTHOR'S DECISIONS" in seen["p"] and "- Old theme" in seen["p"]


def test_run_radar_loads_decisions(tmp_path: Path, monkeypatch, capsys):
    sw.record_decision(tmp_path, "Old theme", "skipped")
    monkeypatch.setattr(sw, "_hn_top", lambda days, limit=40: SIGNALS)
    monkeypatch.setattr(sw, "_reddit_top", lambda days, limit=40: [])
    monkeypatch.setattr(sw, "_radar_web_scan", lambda days: [])
    seen = {}
    monkeypatch.setattr(sw, "call_claude", lambda prompt, **kw: (seen.update(p=prompt), json.dumps(
        {"themes": [{"title": "Old theme revisited", "score": 50, "evidence": EV},
                    {"title": "Fresh", "score": 40, "evidence": EV}], "skipped": []}))[1])
    sw.run_radar(tmp_path, days=14)
    out = capsys.readouterr().out
    assert "Remembering 1 earlier decision(s)" in out
    latest = json.loads((tmp_path / "radar_latest.json").read_text(encoding="utf-8"))
    assert [t["title"] for t in latest["themes"]] == ["Fresh"]


def test_app_decide_and_latest_annotation(tmp_path: Path, monkeypatch):
    os.environ["APP_PASSWORD"] = ""
    import app as a
    monkeypatch.setattr(a, "OUTPUT_DIR", tmp_path)
    c = a.app.test_client()
    (tmp_path / "radar_latest.json").write_text(json.dumps({"themes": [{"title": "T one"}, {"title": "T two"}]}), encoding="utf-8")
    assert c.post("/api/radar/decide", json={"title": "T one", "status": "bogus"}).status_code == 400
    assert c.post("/api/radar/decide", json={"title": "", "status": "approved"}).status_code == 400
    assert c.post("/api/radar/decide", json={"title": "T one", "status": "approved"}).get_json()["status"] == "approved"
    themes = c.get("/api/radar/latest").get_json()["themes"]
    assert themes[0]["decision"] == "approved" and themes[1]["decision"] is None
    assert c.post("/api/radar/decide", json={"title": "T one", "status": "clear"}).get_json()["status"] is None
    assert c.get("/api/radar/latest").get_json()["themes"][0]["decision"] is None
    spawned = {}
    monkeypatch.setattr(a, "_spawn", lambda cmd, **kw: (spawned.update(cmd=cmd), "j")[1])
    c.post("/api/start", json={"topic": "t", "from_theme": "T two"})
    assert spawned["cmd"][spawned["cmd"].index("--from-theme") + 1] == "T two"
    html = c.get("/").get_data(as_text=True)
    assert 'id="fromTheme"' in html and "radar-decide" in html and "/api/radar/decide" in html
