#!/usr/bin/env python3
"""
SEO Writer — minimal web frontend.

Run:
    uv run --with flask --with anthropic --with requests --with markdown --with python-docx app.py
    # or
    pip install flask && python app.py

Then open http://localhost:5000
"""

import base64
import hashlib
import hmac
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from flask import (Flask, Response, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_dotenv():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

# A single high-effort audit call on a 3,500-word article can run for minutes
# with nothing to print. Emit a comment frame while waiting so neither the
# browser nor Fly's edge proxy closes the connection, and only fail on a
# genuinely dead pipeline.
HEARTBEAT_SECS = 15
SILENCE_LIMIT_SECS = 900

# In-memory job store: job_id → queue.Queue
_jobs: dict[str, queue.Queue] = {}
_job_started: dict[str, float] = {}
_jobs_lock = threading.Lock()

# A job now outlives a dropped connection so the browser can reconnect to it.
# Without a sweep, one abandoned tab would leak its queue for the life of the
# process, and the pipeline keeps writing into it.
JOB_RETENTION_SECS = 4 * 3600


def _reap_jobs():
    cutoff = time.time() - JOB_RETENTION_SECS
    with _jobs_lock:
        for jid in [j for j, started in _job_started.items() if started < cutoff]:
            _jobs.pop(jid, None)
            _job_started.pop(jid, None)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
#
# POST /api/start spends real money - roughly fifteen model calls across three
# vendors, two of them high-effort. Deployed without a password that endpoint is
# an open faucet on someone else's card, so set APP_PASSWORD anywhere the app is
# reachable from the internet.

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
APP_USERNAME = os.environ.get("APP_USERNAME", "admin")

# A browser gets a real login form and a session cookie; scripts and curl keep
# working with basic auth against the same password. Either satisfies the gate.
#
# The signing key defaults to something derived from the password, so sessions
# survive a restart without a second secret to manage - and changing the
# password signs everyone out, which is what you want from a password change.
SECRET_KEY = os.environ.get("SECRET_KEY", "")
app.secret_key = SECRET_KEY or hashlib.sha256(
    ("humanly-session-v1:" + APP_PASSWORD).encode()
).hexdigest()

# Fly sets FLY_APP_NAME, and Fly is always HTTPS. Locally the app is plain HTTP,
# where a Secure cookie would never be sent back and the login would loop.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("FLY_APP_NAME")),
)

# Public because a browser must reach them before it can authenticate, and
# because a health check should not need a credential.
_OPEN_PATHS = {"/healthz", "/login"}

# A login form on a public URL is a brute-force target. This is deliberately
# small: a per-IP counter, not a rate-limiting library.
_LOGIN_MAX_ATTEMPTS = 8
_LOGIN_LOCKOUT_SECS = 300
_login_failures: dict[str, list] = {}
_login_lock = threading.Lock()


def _client_ip() -> str:
    fwd = request.headers.get("Fly-Client-IP") or request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() or request.remote_addr or "unknown")


def _locked_out(ip: str) -> int:
    """Seconds remaining on a lockout, or 0."""
    with _login_lock:
        hits = [t for t in _login_failures.get(ip, [])
                if time.time() - t < _LOGIN_LOCKOUT_SECS]
        _login_failures[ip] = hits
        if len(hits) >= _LOGIN_MAX_ATTEMPTS:
            return int(_LOGIN_LOCKOUT_SECS - (time.time() - hits[0])) + 1
    return 0


def _record_failure(ip: str):
    with _login_lock:
        _login_failures.setdefault(ip, []).append(time.time())


def _clear_failures(ip: str):
    with _login_lock:
        _login_failures.pop(ip, None)


def _password_ok(candidate: str) -> bool:
    return hmac.compare_digest(candidate or "", APP_PASSWORD)


def _basic_auth_ok() -> bool:
    auth = request.authorization
    if not auth or auth.type != "basic":
        return False
    # compare_digest on both halves, so neither the username nor the password
    # leaks its length through response timing.
    return (hmac.compare_digest(auth.username or "", APP_USERNAME)
            and _password_ok(auth.password or ""))


def _logged_in() -> bool:
    return session.get("auth") is True


@app.before_request
def require_password():
    if not APP_PASSWORD or request.path in _OPEN_PATHS:
        return None
    # Signed download links carry their own credential (an expiring HMAC), so
    # an automation platform can fetch one finished file without the password.
    if request.path.startswith("/dl/"):
        return None
    if _logged_in() or _basic_auth_ok():
        return None
    # An API caller wants a 401 it can handle, not an HTML login page.
    if request.path.startswith("/api/"):
        return Response(
            "Authentication required.\n", 401,
            {"WWW-Authenticate": 'Basic realm="Humanly", charset="UTF-8"'},
        )
    return redirect(url_for("login", next=request.full_path.rstrip("?")))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("index"))
    if _logged_in():
        return redirect(url_for("index"))

    target = request.args.get("next") or request.form.get("next") or "/"
    # Only ever bounce to a path on this app, never to another host.
    if not target.startswith("/") or target.startswith("//"):
        target = "/"

    error = None
    if request.method == "POST":
        ip = _client_ip()
        wait = _locked_out(ip)
        if wait:
            error = f"Too many attempts. Try again in {wait} seconds."
        elif _password_ok(request.form.get("password", "")):
            _clear_failures(ip)
            session.clear()
            session["auth"] = True
            session.permanent = False
            return redirect(target)
        else:
            _record_failure(ip)
            error = "That password is not right."

    return render_template("login.html", error=error, next=target), (
        200 if error is None else 401
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "protected": bool(APP_PASSWORD)})


def list_articles() -> list[dict]:
    """Return metadata for every generated article, newest first."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    articles = []
    for meta_file in sorted(OUTPUT_DIR.glob("*_meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        slug = meta_file.stem.replace("_meta", "")
        try:
            meta = json.loads(meta_file.read_text())
        except Exception:
            meta = {}

        seo = meta.get("seo_meta", {})
        md_path = OUTPUT_DIR / f"{slug}.md"

        # Glob-based matching: find any html/docx starting with this slug
        # (handles old files saved under different names)
        html_files = sorted(OUTPUT_DIR.glob(f"{slug}*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        docx_files = sorted(OUTPUT_DIR.glob(f"{slug}*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
        html_file = html_files[0].name if html_files else None
        docx_file = docx_files[0].name if docx_files else None
        linkedin_path = OUTPUT_DIR / f"{slug}_linkedin.md"
        video_path = OUTPUT_DIR / f"{slug}_video.md"
        voice_path = OUTPUT_DIR / f"{slug}_voiceover.mp3"
        thumb_path = OUTPUT_DIR / f"{slug}_thumbnail.html"
        review_path = OUTPUT_DIR / f"{slug}_review.json"

        word_count = 0
        if md_path.exists():
            word_count = len(md_path.read_text().split())

        generated_at = meta.get("generated_at", "")
        if generated_at:
            try:
                dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                generated_at = dt.strftime("%b %d, %Y")
            except Exception:
                pass

        articles.append({
            "slug": slug,
            "title": seo.get("title", slug.replace("-", " ").title()),
            "description": seo.get("description", ""),
            "generated_at": generated_at,
            "word_count": word_count,
            "html_file": html_file,
            "docx_file": docx_file,
            "image_count": len(meta.get("images", [])),
            "linkedin_file": linkedin_path.name if linkedin_path.exists() else None,
            "video_file": video_path.name if video_path.exists() else None,
            "voice_file": voice_path.name if voice_path.exists() else None,
            "thumb_file": thumb_path.name if thumb_path.exists() else None,
            "has_review": review_path.exists(),
        })
    return articles


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    articles = list_articles()
    return render_template("index.html", articles=articles)


@app.route("/output/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/api/articles")
def api_articles():
    return jsonify(list_articles())


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------

def read_usage(limit: int = 500) -> list[dict]:
    """Every run the pipeline has logged, newest first."""
    path = OUTPUT_DIR / "usage.jsonl"
    if not path.exists():
        return []
    runs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except ValueError:
            continue          # a torn write should not blank the whole dashboard
    return list(reversed(runs))[:limit]


def usage_rollup(runs: list[dict]) -> dict:
    """Totals overall, per model, and per day."""
    total = {"runs": len(runs), "calls": 0, "input_tokens": 0,
             "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
             "fully_priced": True}
    by_model, by_day = defaultdict(lambda: {"calls": 0, "input_tokens": 0,
                                            "output_tokens": 0, "cost_usd": 0.0}), \
        defaultdict(lambda: {"runs": 0, "total_tokens": 0, "cost_usd": 0.0})

    for r in runs:
        total["calls"] += r.get("calls", 0)
        total["input_tokens"] += r.get("input_tokens", 0)
        total["output_tokens"] += r.get("output_tokens", 0)
        total["total_tokens"] += r.get("total_tokens", 0)
        total["cost_usd"] += r.get("cost_usd", 0.0)
        if not r.get("fully_priced", True):
            total["fully_priced"] = False

        day = (r.get("at") or "")[:10] or "unknown"
        by_day[day]["runs"] += 1
        by_day[day]["total_tokens"] += r.get("total_tokens", 0)
        by_day[day]["cost_usd"] += r.get("cost_usd", 0.0)

        for model, m in (r.get("by_model") or {}).items():
            bucket = by_model[model]
            bucket["calls"] += m.get("calls", 0)
            bucket["input_tokens"] += m.get("input_tokens", 0)
            bucket["output_tokens"] += m.get("output_tokens", 0)
            bucket["cost_usd"] += m.get("cost_usd", 0.0)

    runs_n = max(total["runs"], 1)
    total["avg_tokens_per_run"] = round(total["total_tokens"] / runs_n)
    total["avg_cost_per_run"] = round(total["cost_usd"] / runs_n, 3)
    return {
        "total": total,
        "by_model": dict(sorted(by_model.items(),
                                key=lambda kv: -kv[1]["cost_usd"])),
        "by_day": dict(sorted(by_day.items(), reverse=True)),
    }


@app.route("/api/usage")
def api_usage():
    runs = read_usage()
    return jsonify({**usage_rollup(runs), "runs": runs})


@app.route("/usage")
def usage_dashboard():
    runs = read_usage()
    roll = usage_rollup(runs)
    return render_template("usage.html", runs=runs, **roll)


# ---------------------------------------------------------------------------
# Completion callback + signed downloads
# ---------------------------------------------------------------------------
#
# The browser follows a run over /api/stream/<job_id>, but an automation
# platform (Zapier, n8n, Make) cannot hold an SSE stream open for a ten-minute
# job. So /api/start accepts an optional callback_url: when the pipeline exits,
# the app POSTs one JSON payload there describing what was produced, and echoes
# the caller's external_id so the receiver can find its own record.
#
# The files in that payload are linked through /dl/... - URLs that carry an
# expiring HMAC instead of the app password, so the receiver can fetch them
# without a credential it would otherwise have to store.

DOWNLOAD_TTL_SECS = int(os.environ.get("DOWNLOAD_TTL_SECS", 7 * 24 * 3600))
CALLBACK_TIMEOUT_SECS = 15
CALLBACK_ATTEMPTS = 3


def _public_base_url() -> str:
    """Where the outside world reaches this app. PUBLIC_URL wins; otherwise the
    request's own host, forced to https on Fly where the edge terminates TLS."""
    configured = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if configured:
        return configured
    root = request.url_root.rstrip("/")
    if os.environ.get("FLY_APP_NAME") and root.startswith("http://"):
        root = "https://" + root[len("http://"):]
    return root


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _download_sig(filename: str, exp: int) -> str:
    msg = f"{exp}|{filename}".encode()
    return _b64(hmac.new(app.secret_key.encode(), msg, hashlib.sha256).digest())


def signed_download_url(filename: str, base_url: str,
                        ttl: int = DOWNLOAD_TTL_SECS) -> str:
    exp = int(time.time()) + ttl
    return f"{base_url}/dl/{exp}/{_download_sig(filename, exp)}/{filename}"


@app.route("/dl/<int:exp>/<sig>/<path:filename>")
def signed_download(exp: int, sig: str, filename: str):
    if time.time() > exp:
        return Response("This download link has expired.\n", 410)
    if not hmac.compare_digest(sig.encode(), _download_sig(filename, exp).encode()):
        return Response("Invalid download link.\n", 403)
    return send_from_directory(OUTPUT_DIR, filename)


def _valid_callback_url(url: str) -> bool:
    return bool(re.match(r"^https?://[^\s/]+", url or ""))


def _completion_payload(slug: str | None, external_id: str, status: str,
                        error: str, base_url: str, echo: dict) -> dict:
    payload = {
        "external_id": external_id,
        "status": status,
        "error": error or None,
        "slug": slug,
        "request": echo,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if not slug:
        return payload

    meta_path = OUTPUT_DIR / f"{slug}_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    payload["meta"] = meta.get("seo_meta", {})
    payload["images"] = meta.get("images", [])

    md_path = OUTPUT_DIR / f"{slug}.md"
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8")
        payload["word_count"] = len(text.split())
        # Inline the article so a receiver with no file step still gets it.
        payload["article_md"] = text

    files = {}
    for key, name in {
        "md": f"{slug}.md",
        "html": f"{slug}.html",
        "docx": f"{slug}.docx",
        "meta": f"{slug}_meta.json",
        "linkedin": f"{slug}_linkedin.md",
        "video": f"{slug}_video.md",
        "voiceover": f"{slug}_voiceover.mp3",
        "thumbnail": f"{slug}_thumbnail.html",
        "review_md": f"{slug}_review.md",
        "review_json": f"{slug}_review.json",
        "facts": f"{slug}_facts.json",
        "diagram_png": f"{slug}_diagram_1.png",
        "diagram_svg": f"{slug}_diagram_1.svg",
        "usage": f"{slug}_usage.json",
    }.items():
        if (OUTPUT_DIR / name).exists():
            files[key] = signed_download_url(name, base_url)
    payload["files"] = files

    # The small extras travel inline too - they are what the downstream media
    # steps consume, and a 200-word post is cheaper to embed than to fetch.
    for key, name in {"linkedin_md": f"{slug}_linkedin.md",
                      "video_script_md": f"{slug}_video.md"}.items():
        p = OUTPUT_DIR / name
        if p.exists():
            payload[key] = p.read_text(encoding="utf-8")

    usage_path = OUTPUT_DIR / f"{slug}_usage.json"
    try:
        u = json.loads(usage_path.read_text(encoding="utf-8"))
        payload["usage"] = {k: u.get(k) for k in
                            ("calls", "input_tokens", "output_tokens",
                             "total_tokens", "cost_usd", "fully_priced")
                            if k in u}
    except Exception:
        pass
    return payload


def _post_callback(url: str, payload: dict):
    """Deliver the completion payload, retrying briefly. Runs on its own thread."""
    import requests
    delay = 2
    for attempt in range(1, CALLBACK_ATTEMPTS + 1):
        try:
            r = requests.post(url, json=payload, timeout=CALLBACK_TIMEOUT_SECS)
            if r.status_code < 400:
                print(f"[callback] delivered to {url} ({r.status_code})", flush=True)
                return
            print(f"[callback] attempt {attempt}: {url} answered {r.status_code}",
                  flush=True)
        except Exception as e:
            print(f"[callback] attempt {attempt}: {e}", flush=True)
        time.sleep(delay)
        delay *= 3
    print(f"[callback] gave up on {url} after {CALLBACK_ATTEMPTS} attempts", flush=True)


def _radar_payload(callback: dict, status: str, error: str) -> dict:
    payload = {
        "kind": "radar", "external_id": callback["external_id"], "status": status,
        "error": error or None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    latest = OUTPUT_DIR / "radar_latest.json"
    if status == "done" and latest.exists():
        try:
            radar = json.loads(latest.read_text(encoding="utf-8"))
        except Exception:
            radar = {}
        payload.update({k: radar.get(k) for k in ("generated_at", "days", "signals", "themes", "skipped")})
        stamp = str(radar.get("generated_at") or "")[:10]
        files = {}
        for key, name in {"radar_md": f"radar_{stamp}.md", "radar_json": f"radar_{stamp}.json"}.items():
            if (OUTPUT_DIR / name).exists():
                files[key] = signed_download_url(name, callback["base_url"])
        payload["files"] = files
    return payload


def _new_slug(baseline: set) -> str | None:
    """The article this job wrote: whichever _meta.json did not exist before it."""
    fresh = [p for p in OUTPUT_DIR.glob("*_meta.json") if p.name not in baseline]
    if not fresh:
        return None
    newest = max(fresh, key=lambda p: p.stat().st_mtime)
    return newest.stem[:-len("_meta")]


@app.route("/api/start", methods=["POST"])
def api_start():
    """
    Start a pipeline job. Returns { job_id }.
    Frontend then opens EventSource on /api/stream/<job_id>.

    Optional in the JSON body:
      callback_url  - POSTed a completion payload when the run ends
      external_id   - echoed back in that payload (e.g. an Airtable record id)
    """
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    intent = (data.get("intent") or "").strip()
    take = (data.get("take") or "").strip()[:4000]
    callback_url = (data.get("callback_url") or "").strip()
    external_id = str(data.get("external_id") or "")[:200]
    if callback_url and not _valid_callback_url(callback_url):
        return jsonify({"error": "callback_url must be an http(s) URL"}), 400
    try:
        edition = int(data.get("edition") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "edition must be a number"}), 400
    words = str(data.get("words") or "default")
    if words not in {"default", "1000", "2000"}:
        words = "default"
    linkedin = bool(data.get("linkedin"))
    video = bool(data.get("video"))
    voiceover = bool(data.get("voiceover"))
    thumbnail = bool(data.get("thumbnail"))

    if not topic:
        return jsonify({"error": "topic is required"}), 400

    cmd = [
        sys.executable, str(BASE_DIR / "seo_writer.py"),
        topic,
        "--output-dir", str(OUTPUT_DIR),
        "--edition", str(edition),
        "--words", words,
    ]
    if intent:
        cmd += ["--intent", intent]
    if take:
        cmd += ["--take", take]
    if linkedin:
        cmd.append("--linkedin")
    if video:
        cmd.append("--video")
    if voiceover:
        cmd.append("--voiceover")
    if thumbnail:
        cmd.append("--thumbnail")

    callback = None
    if callback_url:
        OUTPUT_DIR.mkdir(exist_ok=True)
        callback = {
            "url": callback_url,
            "external_id": external_id,
            "base_url": _public_base_url(),
            "article_baseline": {p.name for p in OUTPUT_DIR.glob("*_meta.json")},
            "echo": {"topic": topic, "intent": intent, "take": take, "words": words,
                     "edition": edition, "linkedin": linkedin,
                     "video": video, "voiceover": voiceover, "thumbnail": thumbnail},
        }

    job_id = _spawn(cmd, callback=callback)
    return jsonify({"job_id": job_id, "external_id": external_id or None})


def _spawn(cmd: list[str], review_baseline: set | None = None,
           callback: dict | None = None) -> str:
    """Run seo_writer.py in the background, streaming its output to a job queue.

    Shared by generation and audit: both are the same pipeline script with
    different flags, and both want the same live log.

    `callback`, when given, is {url, external_id, base_url, article_baseline,
    echo}: after the process exits, one completion payload is POSTed to url.
    """
    _reap_jobs()
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    with _jobs_lock:
        _jobs[job_id] = q
        _job_started[job_id] = time.time()

    def notify(status: str, error: str = ""):
        if not callback:
            return
        if callback.get("kind") == "radar":
            payload = _radar_payload(callback, status, error)
        else:
            slug = _new_slug(callback["article_baseline"])
            payload = _completion_payload(slug, callback["external_id"], status,
                                          error, callback["base_url"],
                                          callback["echo"])
        payload["job_id"] = job_id
        threading.Thread(target=_post_callback,
                         args=(callback["url"], payload), daemon=True).start()

    def run():
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ},
            )
            last_error = ""
            tail = deque(maxlen=40)
            for line in proc.stdout:
                line = line.rstrip()
                # seo_writer.py prefixes fatal, already-human-readable failures
                # with "ERROR:" — prefer that over a bare exit code.
                if line.startswith("ERROR:"):
                    last_error = line[len("ERROR:"):].strip()
                tail.append(line)
                q.put(("log", line))
            proc.wait()
            if proc.returncode != 0:
                # The child's output only ever went to the browser, so a crash
                # vanished when the tab closed and the server log showed nothing.
                # Echo the tail so it survives in `flyctl logs`.
                print(f"[job] pipeline exited {proc.returncode}; last output:",
                      flush=True)
                for line in tail:
                    print(f"[job]   {line}", flush=True)
                message = (last_error
                           or f"Pipeline exited with code {proc.returncode}. "
                              f"The server log has the last 40 lines.")
                q.put(("error", message))
                notify("error", message)
                return

            payload = {}
            if review_baseline is not None:
                # Whichever report is new is this job's. Identifying it by
                # difference beats predicting the slug the pipeline will pick.
                fresh = [p for p in OUTPUT_DIR.glob("*_review.json")
                         if p.name not in review_baseline]
                if fresh:
                    newest = max(fresh, key=lambda p: p.stat().st_mtime)
                    payload["review_slug"] = newest.stem[:-len("_review")]
            q.put(("done", json.dumps(payload)))
            notify("done")
        except Exception as e:
            q.put(("error", str(e)))
            notify("error", str(e))

    threading.Thread(target=run, daemon=True).start()
    return job_id


# ---------------------------------------------------------------------------
# Evaluate a draft you already have
# ---------------------------------------------------------------------------

UPLOAD_DIR = OUTPUT_DIR / "uploads"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024          # a 2 MB article is already enormous
ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".docx"}


def _docx_to_markdown(raw: bytes) -> str:
    """Flatten a .docx to text, keeping heading levels so the auditor sees structure."""
    import io
    try:
        from docx import Document
    except ImportError:
        raise ValueError("Reading .docx needs python-docx. Paste the text instead.")
    doc = Document(io.BytesIO(raw))
    lines = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            lines.append("")
            continue
        style = (p.style.name or "").lower()
        if style.startswith("heading"):
            level = "".join(c for c in style if c.isdigit()) or "2"
            lines.append("#" * min(int(level), 6) + " " + text)
        else:
            lines.append(text)
    return "\n".join(lines).strip()


def _draft_from_request() -> tuple[str, str]:
    """The document to audit, as (markdown, source name). Raises ValueError."""
    upload = request.files.get("file")
    if upload and upload.filename:
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(
                f"{suffix or 'That file type'} is not supported. "
                f"Upload {', '.join(sorted(ALLOWED_SUFFIXES))}, or paste the text."
            )
        raw = upload.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError("That file is over 2 MB. Trim it or paste the article body.")
        if suffix == ".docx":
            return _docx_to_markdown(raw), Path(upload.filename).stem
        try:
            return raw.decode("utf-8").strip(), Path(upload.filename).stem
        except UnicodeDecodeError:
            raise ValueError("That file is not UTF-8 text. Save it as .md and retry.")

    pasted = (request.form.get("text") or "").strip()
    if pasted:
        return pasted, ""
    raise ValueError("Paste an article or choose a file to evaluate.")


# ---------------------------------------------------------------------------
# Topic radar: what to write
# ---------------------------------------------------------------------------

def _radar_cmd(days: int) -> list[str]:
    return [sys.executable, str(BASE_DIR / "seo_writer.py"), "--radar",
            "--radar-days", str(days), "--output-dir", str(OUTPUT_DIR)]


@app.route("/api/radar", methods=["POST"])
def api_radar():
    """Start a radar run. Same job stream as an article; the result lands in
    output/radar_latest.json and is read back through /api/radar/latest."""
    data = request.get_json(silent=True) or {}
    try:
        days = max(3, min(60, int(data.get("days") or 14)))
    except (TypeError, ValueError):
        days = 14
    callback_url = (data.get("callback_url") or "").strip()
    if callback_url and not _valid_callback_url(callback_url):
        return jsonify({"error": "callback_url must be an http(s) URL"}), 400
    callback = None
    if callback_url:
        callback = {"kind": "radar", "url": callback_url,
                    "external_id": str(data.get("external_id") or "")[:200],
                    "base_url": _public_base_url()}
    return jsonify({"job_id": _spawn(_radar_cmd(days), callback=callback)})


@app.route("/api/radar/dig", methods=["POST"])
def api_radar_dig():
    """Deep research on one theme of the latest radar (1-based index)."""
    data = request.get_json(silent=True) or {}
    try:
        index = int(data.get("index") or 0)
    except (TypeError, ValueError):
        index = 0
    if index < 1:
        return jsonify({"error": "index must be a theme number, starting at 1"}), 400
    if not (OUTPUT_DIR / "radar_latest.json").exists():
        return jsonify({"error": "run the radar first"}), 400
    cmd = [sys.executable, str(BASE_DIR / "seo_writer.py"), "--dig", str(index),
           "--output-dir", str(OUTPUT_DIR)]
    return jsonify({"job_id": _spawn(cmd)})


@app.route("/api/radar/latest")
def api_radar_latest():
    latest = OUTPUT_DIR / "radar_latest.json"
    if not latest.exists():
        return jsonify({"themes": [], "generated_at": None})
    return Response(latest.read_text(encoding="utf-8"), mimetype="application/json")


# Weekly run. Fly has no cron of its own and the machine stays up
# (min_machines_running = 1), so a thread in the one worker checks hourly.
RADAR_WEEKLY = os.environ.get("RADAR_WEEKLY", "").strip().lower()[:3]
RADAR_CALLBACK_URL = os.environ.get("RADAR_CALLBACK_URL", "").strip()
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _radar_is_stale(max_age_days: int = 6) -> bool:
    latest = OUTPUT_DIR / "radar_latest.json"
    if not latest.exists():
        return True
    try:
        stamp = json.loads(latest.read_text(encoding="utf-8")).get("generated_at", "")
        age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return age.days >= max_age_days
    except Exception:
        return True


def _weekly_radar_loop():
    while True:
        try:
            if (datetime.now(timezone.utc).weekday() == _WEEKDAYS[RADAR_WEEKLY]
                    and _radar_is_stale()):
                print("[radar] weekly run starting", flush=True)
                callback = None
                if RADAR_CALLBACK_URL and _valid_callback_url(RADAR_CALLBACK_URL):
                    callback = {"kind": "radar", "url": RADAR_CALLBACK_URL, "external_id": "weekly",
                                "base_url": os.environ.get("PUBLIC_URL", "").rstrip("/")}
                _spawn(_radar_cmd(14), callback=callback)
        except Exception as e:
            print(f"[radar] weekly check failed: {e}", flush=True)
        time.sleep(3600)


def _start_weekly_radar():
    if RADAR_WEEKLY in _WEEKDAYS:
        threading.Thread(target=_weekly_radar_loop, daemon=True).start()
        print(f"[radar] weekly run scheduled for {RADAR_WEEKLY}", flush=True)


_start_weekly_radar()


@app.route("/api/audit/start", methods=["POST"])
def api_audit_start():
    """Run the three agents over a document the user supplied. Returns { job_id }."""
    try:
        draft, filename = _draft_from_request()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if len(draft.split()) < 50:
        return jsonify({"error": "That draft is too short to audit meaningfully "
                                 "(under 50 words)."}), 400

    topic = (request.form.get("topic") or "").strip() or filename
    intent = (request.form.get("intent") or "").strip()
    try:
        rounds = max(1, min(int(request.form.get("rounds") or 2), 4))
    except ValueError:
        rounds = 2
    apply_fixes = (request.form.get("apply") or "").lower() in {"1", "true", "on", "yes"}

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    draft_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.md"
    draft_path.write_text(draft, encoding="utf-8")

    # Snapshot what already exists so the new report can be identified afterwards,
    # rather than guessing at the slug the pipeline will choose.
    before = {p.name for p in OUTPUT_DIR.glob("*_review.json")}

    cmd = [
        sys.executable, str(BASE_DIR / "seo_writer.py"),
        "--audit", str(draft_path),
        "--output-dir", str(OUTPUT_DIR),
        "--verify-rounds", str(rounds),
    ]
    if topic:
        cmd.append(topic)
    if intent:
        cmd += ["--intent", intent]
    if apply_fixes:
        cmd.append("--apply")

    return jsonify({"job_id": _spawn(cmd, review_baseline=before)})


@app.route("/api/reviews")
def api_reviews():
    return jsonify(list_reviews())


def list_reviews() -> list[dict]:
    """Every verification report on disk, newest first."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = []
    for path in sorted(OUTPUT_DIR.glob("*_review.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        slug = path.stem[:-len("_review")]
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rounds = record.get("rounds") or []
        raised = sum(len(r.get("issues") or []) for r in rounds)
        applied = sum(len(r.get("applied") or []) for r in rounds)
        out.append({
            "slug": slug,
            "outcome": record.get("outcome", ""),
            "rounds": len(rounds),
            "raised": raised,
            "applied": applied,
            "at": record.get("finished_at") or record.get("started_at") or "",
            "agents": {k: v.get("model") for k, v in (record.get("agents") or {}).items()},
        })
    return out


def parse_video_script(text: str) -> list[dict]:
    """Split a generated script into its beats: heading, visual note, narration."""
    beats, current = [], None
    for line in text.splitlines():
        if line.startswith("## Narration only"):
            break
        heading = re.match(r"^##\s+(.*)", line)
        if heading:
            if current:
                beats.append(current)
            current = {"title": heading.group(1).strip(), "visual": "", "lines": []}
            continue
        if current is None:
            continue
        visual = re.match(r"^\*\*Visual:\*\*\s*(.*)", line)
        if visual:
            current["visual"] = visual.group(1).strip()
        elif line.strip() and not line.startswith("---"):
            current["lines"].append(line.strip())
    if current:
        beats.append(current)
    return [b for b in beats if b["lines"] or b["visual"]]


@app.route("/deck/<slug>")
def deck_page(slug):
    """A presentable visual track built from the article's video script."""
    path = OUTPUT_DIR / f"{Path(slug).name}_video.md"
    if not path.exists():
        return render_template("deck.html", beats=None, slug=slug), 404
    beats = parse_video_script(path.read_text(encoding="utf-8"))
    return render_template("deck.html", beats=beats, slug=slug)


@app.route("/review/<slug>")
def review_page(slug):
    path = OUTPUT_DIR / f"{Path(slug).name}_review.json"
    if not path.exists():
        return render_template("review.html", record=None, slug=slug), 404
    record = json.loads(path.read_text(encoding="utf-8"))
    rounds = record.get("rounds") or []
    counts = {
        "rounds": len(rounds),
        "raised": sum(len(r.get("issues") or []) for r in rounds),
        "applied": sum(len(r.get("applied") or []) for r in rounds),
        "disputed": sum(1 for r in rounds
                        for x in (r.get("responses") or [])
                        if x.get("stance") == "dispute"),
    }
    return render_template("review.html", record=record, slug=slug, counts=counts)


@app.route("/api/stream/<job_id>")
def api_stream(job_id):
    """EventSource endpoint — streams log lines then a done/error event."""
    with _jobs_lock:
        q = _jobs.get(job_id)
    if q is None:
        return jsonify({"error": "job not found"}), 404

    def stream():
        # "error" is a reserved EventSource event name: the browser fires it on
        # any connection failure, with no data attached. Sending pipeline
        # failures under that name made a dropped connection and a real failure
        # arrive at the same handler, indistinguishable. They are sent as
        # "failed" instead.
        silent = 0
        finished = False
        try:
            while True:
                try:
                    kind, msg = q.get(timeout=HEARTBEAT_SECS)
                except queue.Empty:
                    silent += HEARTBEAT_SECS
                    if silent >= SILENCE_LIMIT_SECS:
                        minutes = SILENCE_LIMIT_SECS // 60
                        finished = True
                        yield (
                            "event: failed\ndata: "
                            + json.dumps({"message": f"The pipeline stopped "
                                                     f"responding after {minutes} "
                                                     f"minutes."})
                            + "\n\n"
                        )
                        break
                    yield ": keepalive\n\n"
                    continue

                silent = 0
                if kind == "log":
                    yield f"event: log\ndata: {json.dumps({'line': msg})}\n\n"
                elif kind == "done":
                    finished = True
                    yield f"event: done\ndata: {msg or '{}'}\n\n"
                    break
                elif kind == "error":
                    finished = True
                    yield f"event: failed\ndata: {json.dumps({'message': msg})}\n\n"
                    break
        finally:
            # Only forget the job once it actually ended. Dropping it on any
            # disconnect defeated EventSource's own reconnect - the retry hit a
            # 404 and gave up, while the pipeline carried on unwatched.
            if finished:
                with _jobs_lock:
                    _jobs.pop(job_id, None)
                    _job_started.pop(job_id, None)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting SEO Writer UI at http://localhost:{port}")
    app.run(debug=True, port=port, threaded=True)
