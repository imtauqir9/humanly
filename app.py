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
import os as _os
_os.environ.setdefault("ANTHROPIC_API_KEY", _os.environ.get("ANTHROPIC_API_KEY", "unset"))
import seo_writer as sw_decisions  # noqa: E402  (decision helpers only)
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

from flask import (Flask, Response, abort, g, has_app_context, jsonify, redirect,
                   render_template, request, send_from_directory, session, url_for)

import store as st

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
RESEARCH_DIR = BASE_DIR / "research"


def _notes_paths(raw) -> list:
    """`notes` in a run request: file or folder names under the workspace's
    research folder or its output folder, passed to the pipeline as --notes.
    Anything that resolves outside those two folders, or does not exist, is
    dropped."""
    if isinstance(raw, str):
        raw = [raw]
    found = []
    for item in raw or []:
        name = str(item).strip()
        if not name:
            continue
        for base in (notes_dir(), ws_dir()):
            candidate = (base / name).resolve()
            try:
                candidate.relative_to(base.resolve())
            except ValueError:
                continue
            if candidate.exists():
                found.append(str(candidate))
                break
    return found[:12]


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

# Jobs live in the database and their logs on the volume, so a deploy or a
# crash no longer loses track of them. Each pipeline is a separate process; on
# a 1 GB machine two at once is the safe ceiling (video rendering is the heavy
# one), and the rest wait their turn in order.
MAX_CONCURRENT_JOBS = max(1, int(os.environ.get("MAX_CONCURRENT_JOBS", "2") or 2))
JOB_POLL_SECS = 1.0


# ---------------------------------------------------------------------------
# Records: the store, workspaces and their folders
# ---------------------------------------------------------------------------
#
# Each client is a workspace with its own folder, voice, settings and people.
# The default workspace keeps using output/ itself, so everything written
# before workspaces existed is still where it was.

_stores: dict[str, st.Store] = {}
_stores_lock = threading.Lock()
_bootstrapped: set = set()
_resumed: set = set()


def system_dir() -> Path:
    return OUTPUT_DIR / "_system"


def _secrets_key() -> str:
    """The key that encrypts stored client credentials. Kept apart from the
    session key, which follows APP_PASSWORD and would orphan them on rotation."""
    configured = os.environ.get("SECRETS_KEY", "")
    if configured:
        return configured
    path = system_dir() / "secrets.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(st.new_token(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def store() -> st.Store:
    path = str(system_dir() / "humanly.db")
    with _stores_lock:
        s = _stores.get(path)
        if s is None:
            s = _stores[path] = st.Store(Path(path), secret_key=_secrets_key())
            interrupted = s.interrupt_running_jobs()
            if interrupted:
                print(f"[jobs] {interrupted} job(s) were running at the last stop; "
                      f"marked interrupted", flush=True)
        key = (path, APP_USERNAME, APP_PASSWORD)
        if APP_PASSWORD and key not in _bootstrapped:
            s.ensure_bootstrap_admin(APP_USERNAME, APP_PASSWORD)
            _bootstrapped.add(key)
        fresh = path not in _resumed
        _resumed.add(path)
    # Jobs queued before a restart still deserve to run.
    if fresh and s.jobs(limit=1, statuses=("queued",)):
        _start_workers()
    return s


def _current_ws() -> dict | None:
    return getattr(g, "ws", None) if has_app_context() else None


def ws_dir(ws: dict | None = None) -> Path:
    """A workspace's folder. Outside a request (scripts, tests) that is the
    default workspace's, which is output/ itself."""
    ws = ws or _current_ws()
    if ws is None or ws["slug"] == st.DEFAULT_WORKSPACE:
        return OUTPUT_DIR
    return OUTPUT_DIR / "workspaces" / ws["slug"]


def notes_dir(ws: dict | None = None) -> Path:
    ws = ws or _current_ws()
    if ws is None or ws["slug"] == st.DEFAULT_WORKSPACE:
        return RESEARCH_DIR
    return ws_dir(ws) / "notes"


def samples_dir(ws: dict) -> Path:
    return ws_dir(ws) / "samples"


def _ws_by_id(ws_id: int) -> dict:
    return store().workspace_by_id(ws_id) or store().workspace(st.DEFAULT_WORKSPACE)


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
_OPEN_PATHS = {"/healthz", "/login", "/feed.json", "/feed.xml", "/embed.js", "/pipeline"}

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


# Without APP_PASSWORD the app is a private local tool: no sign-in, and
# whoever is at the keyboard acts as the administrator.
_LOCAL_USER = {"id": 0, "username": "local", "name": "Local", "is_admin": 1,
               "bootstrap": 0, "disabled": 0}


def _session_mark(user: dict) -> str:
    """Ties a session to the password it was signed in with, so changing a
    password (or disabling the account) signs that person out everywhere."""
    return hashlib.sha256((user["pw_hash"] + str(user["disabled"])).encode()).hexdigest()[:16]


def _basic_auth_user() -> dict | None:
    auth = request.authorization
    if not auth or auth.type != "basic":
        return None
    return store().check_login(auth.username or "", auth.password or "")


def _session_user() -> dict | None:
    uid = session.get("uid")
    if not uid:
        return None
    user = store().user_by_id(uid)
    if not user or user["disabled"] or session.get("mark") != _session_mark(user):
        return None
    return user


def _pick_workspace(user: dict) -> tuple[dict | None, str | None]:
    """The workspace this request acts in, and the person's role there."""
    s = store()
    wanted = request.args.get("ws") if request.path.startswith("/api/") else None
    wanted = wanted or session.get("ws")
    for slug in (wanted, st.DEFAULT_WORKSPACE):
        if slug:
            ws = s.workspace(slug)
            role = s.role_in(user, ws) if ws else None
            if role:
                return ws, role
    for ws in s.workspaces_for(user):
        role = s.role_in(user, ws)
        if role:
            return ws, role
    return None, None


@app.before_request
def require_password():
    g.user, g.ws, g.role = None, None, None
    if request.path in _OPEN_PATHS:
        return None
    # Signed download links carry their own credential (an expiring HMAC), so
    # an automation platform can fetch one finished file without the password.
    if request.path.startswith("/dl/"):
        return None
    # The /pipeline showcase is public, and so are the diagrams it shows.
    if request.path.startswith("/static/pipeline/"):
        return None

    # A form or fetch from another site must not act with this browser's
    # session. Browsers send Origin on cross-site POSTs; scripts send none.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin", "")
        if origin and origin.split("://", 1)[-1].rstrip("/") != request.host:
            return Response("Cross-site request refused.\n", 403)

    user = _LOCAL_USER if not APP_PASSWORD else (_session_user() or _basic_auth_user())
    if user is None:
        # An API caller wants a 401 it can handle, not an HTML login page.
        if request.path.startswith("/api/"):
            return Response(
                "Authentication required.\n", 401,
                {"WWW-Authenticate": 'Basic realm="Humanly", charset="UTF-8"'},
            )
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    g.user = user
    g.ws, g.role = _pick_workspace(user)
    if g.ws is None and request.path not in ("/logout", "/account"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "You are not a member of any workspace yet."}), 403
        return render_template("no_access.html", user=user), 403
    return None


def can(capability: str) -> bool:
    return g.role in st.CAPABILITIES.get(capability, set())


def needs(capability: str):
    """Refuse the request unless the person's role in this workspace allows it."""
    if not can(capability):
        if request.path.startswith("/api/"):
            abort(Response(json.dumps({"error": "Your role in this workspace does not allow that."}),
                           403, mimetype="application/json"))
        abort(403)


def actor() -> str:
    return (g.user or {}).get("username", "") if getattr(g, "user", None) else ""


def audit(action: str, target: str = "", detail: dict | None = None, ws: dict | None = None):
    ws = ws or getattr(g, "ws", None)
    try:
        store().audit(action, username=actor(), ws_id=ws["id"] if ws else None,
                      target=target, detail=detail, ip=_client_ip() if request else "")
    except Exception as e:  # the log must never take a request down with it
        print(f"[audit] {action} not recorded: {e}", flush=True)


@app.context_processor
def _identity():
    if not getattr(g, "user", None):
        return {}
    workspaces = store().workspaces_for(g.user) if g.user else []
    return {"me": g.user, "current_ws": g.ws, "my_role": g.role,
            "my_workspaces": workspaces, "can": can,
            "role_labels": st.ROLE_LABELS, "auth_on": bool(APP_PASSWORD)}


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("index"))
    if _session_user():
        return redirect(url_for("index"))

    target = request.args.get("next") or request.form.get("next") or "/"
    # Only ever bounce to a path on this app, never to another host.
    if not target.startswith("/") or target.startswith("//"):
        target = "/"

    error = None
    username = (request.form.get("username") or "").strip() or APP_USERNAME
    if request.method == "POST":
        ip = _client_ip()
        wait = _locked_out(ip)
        if wait:
            error = f"Too many attempts. Try again in {wait} seconds."
        else:
            user = store().check_login(username, request.form.get("password", ""))
            if user:
                _clear_failures(ip)
                session.clear()
                session["uid"] = user["id"]
                session["mark"] = _session_mark(user)
                session.permanent = False
                g.user = user
                audit("signed_in", ws={"id": None})
                return redirect(target)
            _record_failure(ip)
            store().audit("sign_in_failed", username=username[:80], ip=ip)
            error = "That password is not right."

    return render_template("login.html", error=error, next=target,
                           username=request.form.get("username", "")), (
        200 if error is None else 401
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/workspace/<slug>")
def switch_workspace(slug):
    ws = store().workspace(slug)
    if not ws or not store().role_in(g.user, ws):
        abort(404)
    session["ws"] = slug
    target = request.args.get("next") or "/"
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    return redirect(target)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "protected": bool(APP_PASSWORD)})


def list_articles(out: Path | None = None) -> list[dict]:
    """Return metadata for every generated article, newest first."""
    ws = _current_ws()
    out = out or ws_dir()
    out.mkdir(parents=True, exist_ok=True)
    states = store().article_states(ws["id"]) if ws and out == ws_dir(ws) else {}
    articles = []
    for meta_file in sorted(out.glob("*_meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        slug = meta_file.stem.replace("_meta", "")
        try:
            meta = json.loads(meta_file.read_text())
        except Exception:
            meta = {}

        seo = meta.get("seo_meta", {})
        md_path = out / f"{slug}.md"

        # Glob-based matching: find any html/docx starting with this slug
        # (handles old files saved under different names)
        html_files = sorted(out.glob(f"{slug}*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        docx_files = sorted(out.glob(f"{slug}*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
        html_file = html_files[0].name if html_files else None
        docx_file = docx_files[0].name if docx_files else None
        linkedin_path = out / f"{slug}_linkedin.md"
        video_path = out / f"{slug}_video.md"
        voice_path = out / f"{slug}_voiceover.mp3"
        mp4_wide = out / f"{slug}_video_16x9.mp4"
        mp4_tall = out / f"{slug}_video_9x16.mp4"
        video_meta = out / f"{slug}_video_meta.md"
        diagram_path = out / f"{slug}_diagram_1.png"
        facts_path = out / f"{slug}_facts.json"
        thumb_path = out / f"{slug}_thumbnail.html"
        review_path = out / f"{slug}_review.json"

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

        state = states.get(slug) or {}
        articles.append({
            "slug": slug,
            "status": state.get("status") or "draft",
            "wp_link": state.get("wp_link"),
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
            "mp4_wide": mp4_wide.name if mp4_wide.exists() else None,
            "mp4_tall": mp4_tall.name if mp4_tall.exists() else None,
            "video_meta": video_meta.name if video_meta.exists() else None,
            "diagram_file": diagram_path.name if diagram_path.exists() else None,
            "facts_file": facts_path.name if facts_path.exists() else None,
            "thumb_file": thumb_path.name if thumb_path.exists() else None,
            "has_review": review_path.exists(),
        })
    return articles


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def list_radars(out: Path | None = None) -> list[dict]:
    """Every dated radar run, newest first, with the briefs dug on its themes."""
    out = out or ws_dir()
    runs = []
    for path in sorted(out.glob("radar_????-??-??.json"), reverse=True):
        date = path.stem[len("radar_"):]
        try:
            radar = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            radar = {}
        themes = radar.get("themes") or []
        briefs = []
        for brief in sorted(out.glob(f"radar_{date}_brief_*.md")):
            try:
                index = int(brief.stem.rsplit("_", 1)[1])
            except ValueError:
                continue
            title = themes[index - 1].get("title", "") if 0 < index <= len(themes) else ""
            briefs.append({"index": index, "file": brief.name, "title": title or brief.name})
        runs.append({
            "date": date, "theme_count": len(themes),
            "top_theme": themes[0].get("title", "") if themes else "",
            "md": f"radar_{date}.md", "json": path.name, "briefs": briefs,
        })
    return runs


RECENT_ON_HOME = 5


@app.route("/")
def index():
    articles = list_articles()
    has_site_notes = g.ws["slug"] != st.DEFAULT_WORKSPACE and notes_dir().exists() \
        and any(notes_dir().glob("*.md"))
    return render_template("index.html", articles=articles[:RECENT_ON_HOME],
                           total_articles=len(articles), has_site_notes=has_site_notes,
                           has_site_pages=(ws_dir() / "site_pages.json").exists(),
                           estimates=job_estimates(g.ws["id"]))


@app.route("/pipeline")
def pipeline():
    """The public showcase: how an article is made, stage by stage."""
    return render_template("pipeline.html")


@app.route("/library")
def library():
    return render_template("library.html", articles=list_articles(), radars=list_radars())


@app.route("/output/<path:filename>")
def serve_output(filename):
    # Only the workspace's own top-level files: never another client's folder,
    # the uploads, or the app's records.
    if "/" in filename or "\\" in filename or filename.startswith("."):
        abort(404)
    return send_from_directory(ws_dir(), filename)


@app.route("/api/articles")
def api_articles():
    return jsonify(list_articles())


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------

def read_usage(limit: int = 500, out: Path | None = None) -> list[dict]:
    """Every run the pipeline has logged, newest first."""
    path = (out or ws_dir()) / "usage.jsonl"
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
    # An administrator bills clients, so they also see every workspace side by side.
    per_workspace = []
    if g.user.get("is_admin"):
        for ws in store().all_workspaces():
            t = usage_rollup(read_usage(out=ws_dir(ws)))["total"]
            per_workspace.append({"ws": ws, **t})
    return render_template("usage.html", runs=runs, per_workspace=per_workspace, **roll)


# ---------------------------------------------------------------------------
# One article: read it, discuss it, edit it, move it towards published
# ---------------------------------------------------------------------------

VERSIONS = "_versions"


def _article_or_404(slug: str) -> tuple[str, Path]:
    slug = Path(slug).name
    md = ws_dir() / f"{slug}.md"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", slug) or not md.exists():
        abort(404)
    return slug, md


def _versions(slug: str) -> list[dict]:
    folder = ws_dir() / VERSIONS
    if not folder.exists():
        return []
    out = []
    for f in sorted(folder.glob(f"{slug}.*.md"), reverse=True):
        stamp = f.name[len(slug) + 1:-3]
        out.append({"name": f.name, "at": stamp.replace("_", " ")[:16]})
    return out


def _rerender(slug: str) -> str:
    """Rebuild the HTML and DOCX as this workspace, so the byline and canonical
    are the client's. Fast and free: no model calls."""
    cmd = [sys.executable, str(BASE_DIR / "seo_writer.py"), "--rerender", slug,
           "--output-dir", str(ws_dir())]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, **pipeline_env(g.ws)}, timeout=120)
    return "" if r.returncode == 0 else (r.stdout + r.stderr)[-400:]


def allowed_moves(state: dict) -> list[str]:
    """The status changes this person may make on this article, in button order."""
    moves = []
    for target in ("in_review", "approved", "changes", "draft"):
        cap, sources = st.TRANSITIONS[target]
        if state["status"] in sources and can(cap):
            moves.append(target)
    return moves


def needs_approval(ws: dict) -> bool:
    return bool((ws.get("settings") or {}).get("require_approval"))


@app.route("/a/<slug>")
def article_page(slug):
    slug, md = _article_or_404(slug)
    out = ws_dir()
    meta = {}
    try:
        meta = json.loads((out / f"{slug}_meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    state = store().article_state(g.ws["id"], slug)
    html_files = sorted(out.glob(f"{slug}*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    artifacts = [(label, name) for label, name in (
        ("Markdown", f"{slug}.md"), ("Word", f"{slug}.docx"), ("Review", f"{slug}_review.md"),
        ("Facts", f"{slug}_facts.json"), ("LinkedIn", f"{slug}_linkedin.md"),
        ("Video script", f"{slug}_video.md")) if (out / name).exists()]
    return render_template(
        "article.html", slug=slug, title=(meta.get("seo_meta") or {}).get("title") or slug,
        description=(meta.get("seo_meta") or {}).get("description") or "",
        markdown=md.read_text(encoding="utf-8"), state=state,
        status_label=st.STATUS_LABELS, moves=allowed_moves(state),
        comments=store().comments(g.ws["id"], slug), versions=_versions(slug),
        html_file=html_files[0].name if html_files else None, artifacts=artifacts,
        has_review=(out / f"{slug}_review.json").exists(),
        approval_required=needs_approval(g.ws), public_url=article_public_url(g.ws, slug),
        wp=wordpress_status(g.ws) if "wordpress_status" in globals() else None,
        msg=request.args.get("msg"), err=request.args.get("err"))


@app.route("/a/<slug>/status", methods=["POST"])
def article_status(slug):
    slug, _ = _article_or_404(slug)
    target = request.form.get("status") or (request.get_json(silent=True) or {}).get("status", "")
    note = (request.form.get("note") or "").strip()
    state = store().article_state(g.ws["id"], slug)
    if target not in allowed_moves(state):
        abort(403)
    store().set_status(g.ws["id"], slug, target, actor())
    line = f"{st.STATUS_LABELS[state['status']]} → {st.STATUS_LABELS[target]}"
    store().add_comment(g.ws["id"], slug, actor(), line + (f"\n\n{note}" if note else ""), kind="status")
    audit("article.status", target=slug, detail={"from": state["status"], "to": target})
    return redirect(url_for("article_page", slug=slug))


@app.route("/a/<slug>/comment", methods=["POST"])
def article_comment(slug):
    needs("comment")
    slug, _ = _article_or_404(slug)
    try:
        store().add_comment(g.ws["id"], slug, actor(), request.form.get("body", ""))
    except ValueError as e:
        return redirect(url_for("article_page", slug=slug, err=str(e)))
    audit("article.commented", target=slug)
    return redirect(url_for("article_page", slug=slug) + "#discussion")


def _save_version(slug: str, md: Path):
    folder = ws_dir() / VERSIONS
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    (folder / f"{slug}.{stamp}.md").write_text(md.read_text(encoding="utf-8"), encoding="utf-8")


def _apply_edit(slug: str, md: Path, text: str, how: str):
    """Keep the old text, write the new, rebuild the HTML, and send an article
    that was already signed off back for approval: what was approved is not
    what will be published any more."""
    _save_version(slug, md)
    md.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
    problem = _rerender(slug)
    state = store().article_state(g.ws["id"], slug)
    store().add_comment(g.ws["id"], slug, actor(), how, kind="edit")
    if needs_approval(g.ws) and state["status"] in ("approved", "published"):
        store().set_status(g.ws["id"], slug, "in_review", actor())
        store().add_comment(g.ws["id"], slug, actor(),
                            f"{st.STATUS_LABELS[state['status']]} → In review\n\nEdited after approval, "
                            f"so it needs approving again.", kind="status")
    audit("article.edited", target=slug, detail={"how": how[:80]})
    return problem


@app.route("/a/<slug>/edit", methods=["POST"])
def article_edit(slug):
    needs("submit")
    slug, md = _article_or_404(slug)
    text = request.form.get("markdown", "")
    if len(text.split()) < 20:
        return redirect(url_for("article_page", slug=slug, err="That is too short to be the article."))
    problem = _apply_edit(slug, md, text, "Edited the text.")
    if problem:
        return redirect(url_for("article_page", slug=slug, err="Saved, but the HTML could not be rebuilt: " + problem))
    return redirect(url_for("article_page", slug=slug, msg="Saved. The previous text is kept under Versions."))


@app.route("/a/<slug>/versions/<name>")
def article_version(slug, name):
    slug, _ = _article_or_404(slug)
    f = ws_dir() / VERSIONS / Path(name).name
    if not f.name.startswith(slug + ".") or not f.exists():
        abort(404)
    return Response(f.read_text(encoding="utf-8"), mimetype="text/plain; charset=utf-8")


@app.route("/a/<slug>/restore", methods=["POST"])
def article_restore(slug):
    needs("submit")
    slug, md = _article_or_404(slug)
    f = ws_dir() / VERSIONS / Path(request.form.get("name", "")).name
    if not f.name.startswith(slug + ".") or not f.exists():
        abort(404)
    problem = _apply_edit(slug, md, f.read_text(encoding="utf-8"), f"Restored the version from {f.name[len(slug) + 1:-3]}.")
    return redirect(url_for("article_page", slug=slug,
                            **({"err": problem} if problem else {"msg": "Restored."})))


# ---------------------------------------------------------------------------
# Workspace settings, people, the audit log
# ---------------------------------------------------------------------------

def _back(endpoint: str, msg: str = "", err: str = "", **kw):
    params = {**kw}
    if msg:
        params["msg"] = msg
    if err:
        params["err"] = err
    return redirect(url_for(endpoint, **params))


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    needs("manage")
    s = store()
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "workspace":
                name = (request.form.get("name") or "").strip()
                settings = {k: (request.form.get(k) or "").strip()[:20000]
                            for k in WORKSPACE_FIELDS if k in request.form}
                if "require_approval" in WORKSPACE_FLAGS:
                    settings["require_approval"] = bool(request.form.get("require_approval"))
                if settings.get("retention_days"):
                    settings["retention_days"] = str(max(0, int(settings["retention_days"])))
                s.update_workspace(g.ws["slug"], name=name or None, settings=settings)
                audit("settings.updated", target=g.ws["name"], detail={"fields": sorted(settings)})
                return _back("settings_page", msg="Settings saved.")
            if action == "intake":
                url = (request.form.get("url") or g.ws["settings"].get("site_url") or "").strip()
                if not url:
                    raise ValueError("Enter the client's website first.")
                if not re.match(r"^https?://", url):
                    url = "https://" + url
                if not g.ws["settings"].get("site_url"):
                    s.update_workspace(g.ws["slug"], settings={"site_url": url.rstrip("/")})
                cmd = [sys.executable, str(BASE_DIR / "site_intake.py"), url,
                       "--out", str(ws_dir())]
                job_id = _spawn(cmd, kind="intake", label=f"Read {url}")
                audit("intake.started", target=url, detail={"job_id": job_id})
                return _back("settings_page", msg="Reading their site. It takes a few minutes; "
                                                  "the jobs list below shows when it is done.")
            if action == "add_member":
                username = (request.form.get("username") or "").strip()
                role = request.form.get("role") or "writer"
                user = s.user_by_name(username)
                created_pw = ""
                if not user:
                    created_pw = st.new_token(12)
                    user = s.create_user(username, created_pw,
                                         name=request.form.get("name") or "")
                    audit("user.created", target=username)
                s.set_role(user["id"], g.ws["id"], role)
                audit("member.added", target=username, detail={"role": role})
                note = f"{username} added as {st.ROLE_LABELS[role]}."
                if created_pw:
                    note += f" Temporary password: {created_pw} - share it privately; it is shown once."
                return _back("settings_page", msg=note)
            if action == "set_role":
                user = s.user_by_id(int(request.form.get("user_id") or 0))
                role = request.form.get("role") or None
                if not user:
                    raise ValueError("No such person.")
                if role is None and user["id"] == g.user.get("id"):
                    raise ValueError("You cannot remove yourself.")
                s.set_role(user["id"], g.ws["id"], role)
                audit("member.removed" if role is None else "member.role_changed",
                      target=user["username"], detail={"role": role})
                return _back("settings_page", msg="Saved.")
        except (ValueError, KeyError) as e:
            return _back("settings_page", err=str(e) or "That did not work.")
        abort(400)

    return render_template("settings.html", ws=g.ws, members=s.members(g.ws["id"]),
                           roles=st.ROLES, msg=request.args.get("msg"),
                           err=request.args.get("err"),
                           ident=ws_identity(g.ws), feed_query=_ws_query(g.ws),
                           site=site_summary(g.ws), jobs=[_job_view(j) for j in s.jobs(g.ws["id"], limit=12)])


def site_summary(ws: dict) -> dict:
    """What site intake found for this workspace, read back from its files."""
    out = ws_dir(ws)
    try:
        summary = json.loads((out / "intake.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = {}
    summary["samples_files"] = sorted(p.name for p in (out / "samples").glob("*.md")) \
        if (out / "samples").exists() else []
    summary["notes_files"] = sorted(p.name for p in (out / "notes").glob("*.md")) \
        if (out / "notes").exists() else []
    summary["has_report"] = (out / "intake_report.md").exists()
    return summary


def _site_pages(ws: dict) -> list[dict]:
    try:
        pages = json.loads((ws_dir(ws) / "site_pages.json").read_text(encoding="utf-8"))
        return pages if isinstance(pages, list) else []
    except (OSError, ValueError):
        return []


_OVERLAP_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "how", "what",
                 "why", "is", "are", "your", "you", "vs", "guide", "best", "from", "by", "it", "its"}


def _topic_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _OVERLAP_STOP}


def topic_overlap(ws: dict, topic: str, limit: int = 3) -> list[dict]:
    """Pages on the client's site, or articles already written here, that cover
    much the same ground. A second page on one topic competes with the first."""
    want = _topic_words(topic)
    if len(want) < 2:
        return []
    candidates = [{"title": p.get("title") or "", "url": p.get("url") or "", "where": "their site"}
                  for p in _site_pages(ws) if p.get("kind") in ("article", "product", None)]
    candidates += [{"title": a["title"], "url": f"/output/{a['html_file']}" if a.get("html_file") else "",
                    "where": "written here"} for a in list_articles(ws_dir(ws))]
    scored = []
    for c in candidates:
        have = _topic_words(c["title"])
        if not have:
            continue
        score = len(want & have) / len(want | have)
        if score >= 0.4:
            scored.append({**c, "score": round(score, 2)})
    scored.sort(key=lambda c: -c["score"])
    return scored[:limit]


@app.route("/api/site/overlap")
def api_site_overlap():
    return jsonify({"matches": topic_overlap(g.ws, request.args.get("topic", ""))})


@app.route("/settings/audit")
def audit_page():
    needs("manage")
    everything = g.user.get("is_admin") and request.args.get("all") == "1"
    rows = store().audit_log(None if everything else g.ws["id"], limit=500)
    return render_template("audit.html", rows=rows, everything=everything)


@app.route("/admin", methods=["GET", "POST"])
def admin_page():
    if not g.user.get("is_admin"):
        abort(403)
    s = store()
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "create_workspace":
                ws = s.create_workspace(request.form.get("name") or "")
                ws_dir(ws).mkdir(parents=True, exist_ok=True)
                if g.user.get("id"):
                    s.set_role(g.user["id"], ws["id"], "owner")
                audit("workspace.created", target=ws["name"], ws=ws)
                session["ws"] = ws["slug"]
                return redirect(url_for("settings_page", msg=f"{ws['name']} is ready. "
                                        "Fill in who it publishes as, then add its people."))
            if action == "create_user":
                pw = st.new_token(12)
                user = s.create_user(request.form.get("username") or "", pw,
                                     name=request.form.get("name") or "",
                                     is_admin=bool(request.form.get("is_admin")))
                audit("user.created", target=user["username"],
                      detail={"admin": bool(user["is_admin"])})
                return _back("admin_page", msg=f"{user['username']} created. Temporary password: "
                                               f"{pw} - share it privately; it is shown once.")
            if action in ("disable", "enable"):
                user = s.user_by_id(int(request.form.get("user_id") or 0))
                if not user or user["bootstrap"]:
                    raise ValueError("That account is managed by the APP_PASSWORD secret.")
                s.set_disabled(user["id"], action == "disable")
                audit(f"user.{action}d", target=user["username"])
                return _back("admin_page", msg="Saved.")
            if action == "reset_password":
                user = s.user_by_id(int(request.form.get("user_id") or 0))
                if not user or user["bootstrap"]:
                    raise ValueError("That account is managed by the APP_PASSWORD secret.")
                pw = st.new_token(12)
                s.set_password(user["id"], pw)
                audit("user.password_reset", target=user["username"])
                return _back("admin_page", msg=f"New password for {user['username']}: {pw} - "
                                               f"share it privately; it is shown once.")
        except (ValueError, KeyError) as e:
            return _back("admin_page", err=str(e) or "That did not work.")
        abort(400)

    workspaces = []
    for ws in s.all_workspaces():
        workspaces.append({**ws, "articles": len(list(ws_dir(ws).glob("*_meta.json")))
                           if ws_dir(ws).exists() else 0,
                           "members": len(s.members(ws["id"]))})
    with s._conn() as c:
        users = [dict(r) for r in c.execute(
            "SELECT id, username, name, is_admin, bootstrap, disabled, created_at FROM users "
            "ORDER BY username COLLATE NOCASE").fetchall()]
    return render_template("admin.html", workspaces=workspaces, users=users,
                           msg=request.args.get("msg"), err=request.args.get("err"))


@app.route("/account", methods=["GET", "POST"])
def account_page():
    user = g.user
    msg = err = None
    if request.method == "POST":
        if not user.get("id") or user.get("bootstrap"):
            err = "This account's password is the APP_PASSWORD secret; change it there."
        elif not store().check_login(user["username"], request.form.get("current", "")):
            err = "Your current password is not right."
        elif request.form.get("new") != request.form.get("confirm"):
            err = "The two new passwords do not match."
        else:
            try:
                store().set_password(user["id"], request.form.get("new", ""))
                fresh = store().user_by_id(user["id"])
                session["mark"] = _session_mark(fresh)
                audit("user.password_changed", target=user["username"])
                msg = "Password changed. Other sessions are signed out."
            except ValueError as e:
                err = str(e)
    return render_template("account.html", msg=msg, err=err)


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


# ---------------------------------------------------------------------------
# Public feed: import published articles into another site
# ---------------------------------------------------------------------------
#
# A portfolio site has no login and no reason to hold this app's password, so
# the feed and the embed widget are public read-only endpoints - the same
# trust level as a signed /dl/ link, just for the whole catalog instead of one
# file. JSON Feed (feed.json) and RSS (feed.xml) cover the two things a static
# site, a build script, or a no-code importer (Zapier, IFTTT, a WordPress RSS
# importer) is likely to already speak; /embed.js is for a site with no build
# step at all - paste a <div> and a <script src>, done.

FEED_LINK_TTL_SECS = int(os.environ.get("FEED_LINK_TTL_SECS", 30 * 24 * 3600))
FEED_DEFAULT_LIMIT = 50
FEED_MAX_LIMIT = 200


def _rfc822(dt_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_iso.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def ws_identity(ws: dict) -> dict:
    """Who a workspace publishes as and where its articles live. The default
    workspace falls back to the environment (SITE_URL, AUTHOR_NAME, ...) as it
    always has; a client workspace never inherits the studio owner's name."""
    s = ws.get("settings") or {}
    default = ws["slug"] == st.DEFAULT_WORKSPACE

    def pick(key: str, env_value: str) -> str:
        value = str(s.get(key) or "").strip()
        return value or (env_value if default else "")

    return {
        "site_url": pick("site_url", sw_decisions.SITE_URL).rstrip("/"),
        "author_name": pick("author_name", sw_decisions.AUTHOR_NAME) or ws["name"],
        "author_url": pick("author_url", sw_decisions.AUTHOR_URL),
        "url_pattern": str(s.get("url_pattern") or "").strip() or "{site}/{slug}",
    }


def article_public_url(ws: dict, slug: str) -> str:
    """Where the article will live on the client's own site, or "" when the
    workspace has no site yet. A wrong URL is worse than none."""
    ident = ws_identity(ws)
    if not ident['site_url']:
        return ""
    return ident["url_pattern"].replace("{site}", ident['site_url']).replace("{slug}", slug)


def _rel(out: Path, name: str) -> str:
    """A workspace file's path under output/, which is what /dl/ links sign."""
    return (out / name).relative_to(OUTPUT_DIR).as_posix()


def _feed_article_url(ws: dict, slug: str, html_file: str | None, base_url: str, out: Path) -> str:
    """The article's page on the workspace's own site once it has one; until
    then, a signed link straight to the app's own rendered HTML, which works today."""
    public = article_public_url(ws, slug)
    if public:
        return public
    if html_file:
        return signed_download_url(_rel(out, html_file), base_url, ttl=FEED_LINK_TTL_SECS)
    return f"{base_url}/library"


def _feed_image_url(meta: dict, slug: str, base_url: str, out: Path) -> str | None:
    for img in meta.get("images", []) or []:
        url = img.get("url", "")
        if sw_decisions.usable_image_url(url):
            return url
    diagram = out / f"{slug}_diagram_1.png"
    if diagram.exists():
        return signed_download_url(_rel(out, diagram.name), base_url, ttl=FEED_LINK_TTL_SECS)
    return None


def _feed_content_html(slug: str, out: Path) -> str | None:
    """The article's own rendered body, so an importer needs no second fetch."""
    html_files = sorted(out.glob(f"{slug}*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not html_files:
        return None
    try:
        text = html_files[0].read_text(encoding="utf-8")
    except Exception:
        return None
    m = re.search(r"<body[^>]*>(.*)</body>", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _feed_ws() -> dict:
    ws = store().workspace(request.args.get("ws") or st.DEFAULT_WORKSPACE)
    if not ws:
        abort(404)
    return ws


def feed_items(base_url: str, limit: int = FEED_DEFAULT_LIMIT, include_content: bool = True,
               ws: dict | None = None) -> list[dict]:
    ws = ws or store().workspace(st.DEFAULT_WORKSPACE)
    out = ws_dir(ws)
    out.mkdir(parents=True, exist_ok=True)
    # A client's feed carries only what the client signed off. The studio's own
    # feed keeps working as before, approval or not.
    states = store().article_states(ws["id"])
    only_cleared = ws["slug"] != st.DEFAULT_WORKSPACE
    author = ws_identity(ws)["author_name"]
    items = []
    for meta_file in sorted(out.glob("*_meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if len(items) >= limit:
            break
        slug = meta_file.stem[:-len("_meta")]
        if only_cleared and (states.get(slug) or {}).get("status") not in ("approved", "published"):
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        seo = meta.get("seo_meta") or {}
        title = seo.get("title") or slug.replace("-", " ").title()
        html_files = sorted(out.glob(f"{slug}*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        html_file = html_files[0].name if html_files else None
        published = meta.get("generated_at") or datetime.now(timezone.utc).isoformat()
        md_path = out / f"{slug}.md"
        word_count = len(md_path.read_text(encoding="utf-8").split()) if md_path.exists() else None
        item = {
            "id": slug,
            "slug": slug,
            "title": title,
            "summary": seo.get("description", ""),
            "url": _feed_article_url(ws, slug, html_file, base_url, out),
            "image": _feed_image_url(meta, slug, base_url, out),
            "date_published": published,
            "author": author,
            "word_count": word_count,
        }
        if include_content:
            item["content_html"] = _feed_content_html(slug, out)
        items.append(item)
    return items


def _ws_query(ws: dict) -> str:
    return "" if ws["slug"] == st.DEFAULT_WORKSPACE else f"?ws={ws['slug']}"


@app.route("/feed.json")
def feed_json():
    base_url = _public_base_url()
    try:
        limit = min(FEED_MAX_LIMIT, max(1, int(request.args.get("limit", FEED_DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        limit = FEED_DEFAULT_LIMIT
    include_content = request.args.get("content", "1") != "0"
    ws = _feed_ws()
    ident = ws_identity(ws)
    items = feed_items(base_url, limit=limit, include_content=include_content, ws=ws)
    feed = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": f"{ident['author_name']} — Articles",
        "home_page_url": ident['author_url'] or ident['site_url'] or base_url,
        "feed_url": f"{base_url}/feed.json{_ws_query(ws)}",
        "description": f"Articles written by {ident['author_name']}, published via Humanly.",
        "author": {"name": ident['author_name'], "url": ident['author_url']},
        "items": [{
            "id": it["id"], "url": it["url"], "title": it["title"],
            "summary": it["summary"],
            **({"content_html": it["content_html"]} if it.get("content_html") else
               {"content_text": it["summary"] or it["title"]}),
            **({"image": it["image"]} if it["image"] else {}),
            "date_published": it["date_published"],
            "authors": [{"name": it["author"]}],
            "_word_count": it["word_count"],
        } for it in items],
    }
    resp = jsonify(feed)
    resp.headers["Content-Type"] = "application/feed+json; charset=utf-8"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/feed.xml")
def feed_rss():
    base_url = _public_base_url()
    try:
        limit = min(FEED_MAX_LIMIT, max(1, int(request.args.get("limit", FEED_DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        limit = FEED_DEFAULT_LIMIT
    ws = _feed_ws()
    ident = ws_identity(ws)
    items = feed_items(base_url, limit=limit, include_content=True, ws=ws)
    site = ident['author_url'] or ident['site_url'] or base_url
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{sw_decisions._esc(ident['author_name'])} — Articles</title>",
        f"<link>{sw_decisions._esc(site)}</link>",
        f'<atom:link href="{sw_decisions._esc(base_url)}/feed.xml{sw_decisions._esc(_ws_query(ws))}" rel="self" type="application/rss+xml"/>',
        f"<description>Articles written by {sw_decisions._esc(ident['author_name'])}, published via Humanly.</description>",
        "<language>en</language>",
    ]
    for it in items:
        parts.append("<item>")
        parts.append(f"<title>{sw_decisions._esc(it['title'])}</title>")
        parts.append(f"<link>{sw_decisions._esc(it['url'])}</link>")
        parts.append(f'<guid isPermaLink="false">{sw_decisions._esc(it["id"])}</guid>')
        parts.append(f"<pubDate>{_rfc822(it['date_published'])}</pubDate>")
        parts.append(f"<description>{sw_decisions._esc(it['summary'])}</description>")
        if it.get("content_html"):
            parts.append(f"<content:encoded><![CDATA[{it['content_html']}]]></content:encoded>")
        if it.get("image"):
            parts.append(f'<enclosure url="{sw_decisions._esc(it["image"])}" type="image/jpeg"/>')
        parts.append("</item>")
    parts += ["</channel>", "</rss>"]
    resp = Response("\n".join(parts), mimetype="application/rss+xml")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/embed.js")
def embed_js():
    """A dependency-free widget: paste one <div> and this <script src> into any
    HTML page (no build step, no framework) and it renders an article grid
    from /feed.json. data-limit, data-target and data-workspace on the <script>
    tag configure it."""
    base_url = _public_base_url()
    js = """(function() {
  var thisScript = document.currentScript;
  var limit = (thisScript && thisScript.getAttribute('data-limit')) || 6;
  var targetSel = (thisScript && thisScript.getAttribute('data-target')) || '#humanly-articles';
  var ws = thisScript && thisScript.getAttribute('data-workspace');
  var feedUrl = '%(base)s/feed.json?limit=' + limit + '&content=0' + (ws ? '&ws=' + encodeURIComponent(ws) : '');

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
    });
  }

  function render(target, feed) {
    var css = '.humanly-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif}' +
      '.humanly-card{display:flex;flex-direction:column;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;text-decoration:none;color:inherit;background:#fff;transition:box-shadow .15s}' +
      '.humanly-card:hover{box-shadow:0 8px 24px rgba(16,24,40,.08)}' +
      '.humanly-card img{width:100%%;height:150px;object-fit:cover;background:#f4f5f7}' +
      '.humanly-card-body{padding:14px 16px;display:flex;flex-direction:column;gap:6px}' +
      '.humanly-card-title{font-size:15px;font-weight:700;line-height:1.4;color:#15171a}' +
      '.humanly-card-desc{font-size:13px;color:#3f4650;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}' +
      '.humanly-card-date{font-size:12px;color:#6b7280}';
    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    var grid = document.createElement('div');
    grid.className = 'humanly-grid';
    (feed.items || []).forEach(function(item) {
      var a = document.createElement('a');
      a.className = 'humanly-card';
      a.href = item.url;
      a.target = '_blank';
      a.rel = 'noopener';
      var img = item.image ? '<img src="' + esc(item.image) + '" alt="">' : '';
      var date = item.date_published ? new Date(item.date_published).toLocaleDateString(undefined, {year:'numeric',month:'short',day:'numeric'}) : '';
      a.innerHTML = img +
        '<div class="humanly-card-body">' +
        '<div class="humanly-card-title">' + esc(item.title) + '</div>' +
        '<div class="humanly-card-desc">' + esc(item.summary) + '</div>' +
        '<div class="humanly-card-date">' + esc(date) + '</div>' +
        '</div>';
      grid.appendChild(a);
    });
    target.innerHTML = '';
    target.appendChild(grid);
  }

  function boot() {
    var target = document.querySelector(targetSel);
    if (!target) return;
    fetch(feedUrl).then(function(r) { return r.json(); }).then(function(feed) {
      render(target, feed);
    }).catch(function() {
      target.textContent = 'Articles could not be loaded.';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
""" % {"base": base_url}
    resp = Response(js, mimetype="application/javascript; charset=utf-8")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


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
                        error: str, base_url: str, echo: dict,
                        out: Path | None = None) -> dict:
    out = out or OUTPUT_DIR
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

    meta_path = out / f"{slug}_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    payload["meta"] = meta.get("seo_meta", {})
    payload["images"] = meta.get("images", [])

    md_path = out / f"{slug}.md"
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
        "video_16x9": f"{slug}_video_16x9.mp4",
        "video_9x16": f"{slug}_video_9x16.mp4",
        "captions": f"{slug}_captions.srt",
        "video_meta": f"{slug}_video_meta.md",
        "thumbnail": f"{slug}_thumbnail.html",
        "review_md": f"{slug}_review.md",
        "review_json": f"{slug}_review.json",
        "facts": f"{slug}_facts.json",
        "diagram_png": f"{slug}_diagram_1.png",
        "diagram_svg": f"{slug}_diagram_1.svg",
        "usage": f"{slug}_usage.json",
    }.items():
        if (out / name).exists():
            files[key] = signed_download_url(_rel(out, name), base_url)
    payload["files"] = files

    # The small extras travel inline too - they are what the downstream media
    # steps consume, and a 200-word post is cheaper to embed than to fetch.
    for key, name in {"linkedin_md": f"{slug}_linkedin.md",
                      "video_script_md": f"{slug}_video.md",
                      "video_meta_md": f"{slug}_video_meta.md"}.items():
        p = out / name
        if p.exists():
            payload[key] = p.read_text(encoding="utf-8")

    usage_path = out / f"{slug}_usage.json"
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
    out = Path(callback.get("out") or OUTPUT_DIR)
    latest = out / "radar_latest.json"
    if status == "done" and latest.exists():
        try:
            radar = json.loads(latest.read_text(encoding="utf-8"))
        except Exception:
            radar = {}
        payload.update({k: radar.get(k) for k in ("generated_at", "days", "signals", "themes", "skipped")})
        stamp = str(radar.get("generated_at") or "")[:10]
        files = {}
        for key, name in {"radar_md": f"radar_{stamp}.md", "radar_json": f"radar_{stamp}.json"}.items():
            if (out / name).exists():
                files[key] = signed_download_url(_rel(out, name), callback["base_url"])
        payload["files"] = files
    return payload


def _new_slug(baseline: set, out: Path | None = None) -> str | None:
    """The article this job wrote: whichever _meta.json did not exist before it."""
    fresh = [p for p in (out or OUTPUT_DIR).glob("*_meta.json") if p.name not in baseline]
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
    notes = _notes_paths(data.get("notes"))
    if not notes and data.get("use_site_notes", True) and g.ws["slug"] != st.DEFAULT_WORKSPACE \
            and any(notes_dir().glob("*.md")):
        notes = [str(notes_dir())]
    resolve_gaps = bool(data.get("resolve_gaps"))
    from_theme = (data.get("from_theme") or "").strip()[:140]
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
    mp4 = bool(data.get("mp4"))
    thumbnail = bool(data.get("thumbnail"))

    if not topic:
        return jsonify({"error": "topic is required"}), 400
    needs("run")

    cmd = [
        sys.executable, str(BASE_DIR / "seo_writer.py"),
        topic,
        "--output-dir", str(ws_dir()),
        "--edition", str(edition),
        "--words", words,
    ]
    if intent:
        cmd += ["--intent", intent]
    if take:
        cmd += ["--take", take]
    if notes:
        cmd += ["--notes", *notes]
    if resolve_gaps:
        cmd.append("--resolve-gaps")
    if from_theme:
        cmd += ["--from-theme", from_theme]
    if linkedin:
        cmd.append("--linkedin")
    if video:
        cmd.append("--video")
    if voiceover:
        cmd.append("--voiceover")
    if mp4:
        cmd.append("--mp4")
    if thumbnail:
        cmd.append("--thumbnail")

    callback = None
    if callback_url:
        callback = {
            "url": callback_url,
            "external_id": external_id,
            "base_url": _public_base_url(),
            "echo": {"topic": topic, "intent": intent, "take": take, "words": words,
                     "edition": edition, "linkedin": linkedin,
                     "video": video, "voiceover": voiceover, "mp4": mp4, "thumbnail": thumbnail},
        }

    job_id = _spawn(cmd, callback=callback, kind="article", label=topic)
    audit("article.started", target=topic, detail={"job_id": job_id, "words": words})
    return jsonify({"job_id": job_id, "external_id": external_id or None})


# ---------------------------------------------------------------------------
# Jobs: a queue in the database, a log on the volume, a few workers
# ---------------------------------------------------------------------------

_workers_started: set = set()
_workers_lock = threading.Lock()
# Workers sleep until a job is queued, with a slow fallback check: an idle app
# should not be opening its database every second.
_wake = threading.Event()
IDLE_CHECK_SECS = 30
TERMINAL = ("done", "failed", "interrupted")


def _job_log(job_id: str) -> Path:
    return system_dir() / "jobs" / f"{job_id}.log"


def _spawn(cmd: list[str], review_baseline: set | None = None,
           callback: dict | None = None, kind: str = "article", label: str = "",
           ws: dict | None = None) -> str:
    """Queue seo_writer.py to run in the background. Returns the job id at once;
    the browser follows the log over /api/stream/<job_id>.

    Shared by generation, audit, the radar and site intake: all are the same
    kind of script with different flags, and all want the same live log.

    `callback`, when given, is {url, external_id, base_url, echo} (plus
    kind="radar" for a radar run): after the process exits, one completion
    payload is POSTed to url. `review_baseline` is accepted for older callers;
    the worker now takes its own snapshot when the job actually starts.
    """
    ws = ws or getattr(g, "ws", None) or store().workspace(st.DEFAULT_WORKSPACE)
    job_id = str(uuid.uuid4())
    by = actor() if getattr(g, "user", None) else "scheduler"
    store().add_job(job_id, ws["id"], kind, label or kind, cmd, by,
                    extra={"callback": callback})
    _start_workers()
    _wake.set()
    return job_id


def _start_workers():
    key = str(system_dir())
    with _workers_lock:
        if key in _workers_started:
            return
        _workers_started.add(key)
    for n in range(MAX_CONCURRENT_JOBS):
        threading.Thread(target=_worker_loop, args=(key,), name=f"job-worker-{n}",
                         daemon=True).start()


def _worker_loop(key: str):
    while True:
        try:
            if str(system_dir()) != key:   # the output folder moved (tests do this)
                return
            job = store().claim_next_job()
            if job is None:
                _wake.wait(IDLE_CHECK_SECS)
                _wake.clear()
                continue
            _run_job(job)
            _wake.set()   # a finished job may unblock another in the same workspace
        except Exception as e:
            print(f"[jobs] worker error: {e}", flush=True)
            time.sleep(JOB_POLL_SECS)


# What a workspace can say about itself. Text fields, all optional.
WORKSPACE_FIELDS = ("site_url", "url_pattern", "author_name", "author_url", "author_bio",
                    "brand_guide", "brand_cta", "radar_lens", "retention_days")
WORKSPACE_FLAGS = ("require_approval",)


def pipeline_env(ws: dict) -> dict:
    """Environment overrides that make the pipeline write as this workspace.

    A client workspace sets every key, empty or not, so nothing of the studio
    owner's - byline, newsletter greeting, sign-off, voice - can leak into a
    client's article. The default workspace overrides only what its settings
    fill in, and otherwise behaves exactly as before workspaces existed."""
    s = ws.get("settings") or {}
    out = ws_dir(ws)
    ident = ws_identity(ws)

    def val(key: str) -> str:
        return str(s.get(key) or "").strip()

    env = {"WEB_CALL_DEBUG_DIR": str(out)}
    if ws["slug"] == st.DEFAULT_WORKSPACE:
        for key, var in (("site_url", "SITE_URL"), ("url_pattern", "ARTICLE_URL_PATTERN"),
                         ("author_name", "AUTHOR_NAME"), ("author_url", "AUTHOR_URL"),
                         ("author_bio", "AUTHOR_BIO"), ("brand_guide", "BRAND_GUIDE"),
                         ("radar_lens", "RADAR_LENS")):
            if val(key):
                env[var] = val(key)
        if "brand_cta" in s:
            env["BRAND_CTA"] = val("brand_cta")
    else:
        name = ident["author_name"]
        env.update({
            "SITE_URL": ident["site_url"],
            "ARTICLE_URL_PATTERN": ident["url_pattern"],
            "AUTHOR_NAME": name,
            "AUTHOR_URL": ident["author_url"],
            "AUTHOR_BIO": val("author_bio") or f"{name}, writing for its own readers.",
            "BRAND_GUIDE": val("brand_guide"),
            "BRAND_CTA": val("brand_cta"),
            "BRAND_INTRO": "",
            "RADAR_LENS": val("radar_lens") or f"the readers of {ws['name']}",
            "STYLE_SAMPLES_DIR": str(samples_dir(ws)),
        })
        # Only what is live on the client's site may be linked to.
        live = {slug: state.get("wp_link") or article_public_url(ws, slug)
                for slug, state in store().article_states(ws["id"]).items()
                if state.get("status") == "published"}
        published_file = out / "_published.json"
        out.mkdir(parents=True, exist_ok=True)
        published_file.write_text(json.dumps(live), encoding="utf-8")
        env["PUBLISHED_FILE"] = str(published_file)
    pages = out / "site_pages.json"
    if pages.exists():
        env["SITE_PAGES_FILE"] = str(pages)
    return env


def _run_job(job: dict):
    ws = _ws_by_id(job["workspace_id"])
    out = ws_dir(ws)
    out.mkdir(parents=True, exist_ok=True)
    log_path = _job_log(job["id"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    callback = (job.get("extra") or {}).get("callback")
    # Whichever file is new after the run is this job's. Snapshotting when the
    # job starts (one job per workspace runs at a time) beats predicting the slug.
    meta_before = {p.name for p in out.glob("*_meta.json")}
    review_before = {p.name for p in out.glob("*_review.json")}

    def notify(status: str, error: str = ""):
        if not callback:
            return
        if callback.get("kind") == "radar":
            payload = _radar_payload({**callback, "out": str(out)}, status, error)
        else:
            slug = _new_slug(meta_before, out)
            payload = _completion_payload(slug, callback.get("external_id", ""), status,
                                          error, callback["base_url"],
                                          callback.get("echo") or {}, out=out)
        payload["job_id"] = job["id"]
        threading.Thread(target=_post_callback,
                         args=(callback["url"], payload), daemon=True).start()

    with open(log_path, "a", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(
                job["cmd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, **pipeline_env(ws)},
            )
            last_error = ""
            tail = deque(maxlen=40)
            for line in proc.stdout:
                line = line.rstrip()
                # seo_writer.py prefixes fatal, already-human-readable failures
                # with "ERROR:" - prefer that over a bare exit code.
                if line.startswith("ERROR:"):
                    last_error = line[len("ERROR:"):].strip()
                tail.append(line)
                log.write(line + "\n")
                log.flush()
            proc.wait()
            if proc.returncode != 0:
                # Echo the tail so a crash survives in `flyctl logs` as well.
                print(f"[job] {job['kind']} {job['id']} exited {proc.returncode}; last output:",
                      flush=True)
                for line in tail:
                    print(f"[job]   {line}", flush=True)
                message = (last_error
                           or f"Pipeline exited with code {proc.returncode}. "
                              f"The server log has the last 40 lines.")
                store().finish_job(job["id"], "failed", error=message)
                store().audit("job.failed", username=job["created_by"], ws_id=ws["id"],
                              target=job["label"], detail={"job_id": job["id"], "kind": job["kind"],
                                                           "error": message[:300]})
                notify("error", message)
                return

            result = {}
            fresh_reviews = [p for p in out.glob("*_review.json") if p.name not in review_before]
            if job["kind"] == "audit" and fresh_reviews:
                newest = max(fresh_reviews, key=lambda p: p.stat().st_mtime)
                result["review_slug"] = newest.stem[:-len("_review")]
            if job["kind"] == "article":
                slug = _new_slug(meta_before, out)
                if slug:
                    result["slug"] = slug
                    state = store().article_state(ws["id"], slug)
                    if not state.get("updated_at"):
                        store().set_status(ws["id"], slug, "draft", job["created_by"])
            store().finish_job(job["id"], "done", result=result)
            store().audit(f"{job['kind']}.finished", username=job["created_by"], ws_id=ws["id"],
                          target=result.get("slug") or job["label"],
                          detail={"job_id": job["id"]})
            notify("done")
        except Exception as e:
            log.write(f"ERROR: {e}\n")
            store().finish_job(job["id"], "failed", error=str(e))
            notify("error", str(e))


def job_estimates(ws_id: int | None = None) -> dict:
    """Typical minutes per kind of job, from the runs this app has timed."""
    durations = defaultdict(list)
    for j in store().jobs(ws_id, limit=200, statuses=("done",)):
        try:
            secs = (datetime.fromisoformat(j["finished_at"])
                    - datetime.fromisoformat(j["started_at"])).total_seconds()
        except (TypeError, ValueError):
            continue
        durations[j["kind"]].append(secs)
    out = {}
    for kind, secs in durations.items():
        secs.sort()
        out[kind] = {"runs": len(secs), "median_minutes": round(secs[len(secs) // 2] / 60, 1)}
    return out


def _job_view(j: dict) -> dict:
    view = {k: j.get(k) for k in ("id", "kind", "label", "status", "created_by", "created_at",
                                  "started_at", "finished_at", "error", "result")}
    if j["status"] == "queued":
        view["ahead"] = store().queue_position(j["id"])
    try:
        secs = (datetime.fromisoformat(j["finished_at"])
                - datetime.fromisoformat(j["started_at"])).total_seconds()
        view["minutes"] = f"{secs / 60:.1f} min"
    except (TypeError, ValueError):
        view["minutes"] = None
    return view


@app.route("/api/jobs")
def api_jobs():
    jobs = store().jobs(g.ws["id"], limit=50)
    return jsonify({"jobs": [_job_view(j) for j in jobs],
                    "estimates": job_estimates(g.ws["id"])})


@app.route("/api/jobs/<job_id>/retry", methods=["POST"])
def api_job_retry(job_id):
    needs("run")
    job = store().job(job_id)
    if not job or job["workspace_id"] != g.ws["id"]:
        return jsonify({"error": "job not found"}), 404
    if job["status"] not in ("interrupted", "failed"):
        return jsonify({"error": "only a failed or interrupted job can be retried"}), 400
    _job_log(job_id).unlink(missing_ok=True)
    store().requeue_job(job_id)
    audit("job.retried", target=job["label"], detail={"job_id": job_id})
    _start_workers()
    _wake.set()
    return jsonify({"job_id": job_id})


# ---------------------------------------------------------------------------
# Evaluate a draft you already have
# ---------------------------------------------------------------------------

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

def _radar_cmd(days: int, out: Path | None = None) -> list[str]:
    return [sys.executable, str(BASE_DIR / "seo_writer.py"), "--radar",
            "--radar-days", str(days), "--output-dir", str(out or ws_dir())]


@app.route("/api/radar", methods=["POST"])
def api_radar():
    """Start a radar run. Same job stream as an article; the result lands in
    output/radar_latest.json and is read back through /api/radar/latest."""
    needs("run")
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
    audit("radar.started", detail={"days": days})
    return jsonify({"job_id": _spawn(_radar_cmd(days), callback=callback, kind="radar",
                                     label=f"Radar, last {days} days")})


@app.route("/api/radar/dig", methods=["POST"])
def api_radar_dig():
    """Deep research on one theme of the latest radar (1-based index)."""
    needs("run")
    data = request.get_json(silent=True) or {}
    try:
        index = int(data.get("index") or 0)
    except (TypeError, ValueError):
        index = 0
    if index < 1:
        return jsonify({"error": "index must be a theme number, starting at 1"}), 400
    if not (ws_dir() / "radar_latest.json").exists():
        return jsonify({"error": "run the radar first"}), 400
    cmd = [sys.executable, str(BASE_DIR / "seo_writer.py"), "--dig", str(index),
           "--output-dir", str(ws_dir())]
    audit("dig.started", detail={"theme": index})
    return jsonify({"job_id": _spawn(cmd, kind="dig", label=f"Dig in on theme {index}")})


@app.route("/api/radar/latest")
def api_radar_latest():
    """The latest radar, each theme annotated with the author's decision."""
    latest = ws_dir() / "radar_latest.json"
    if not latest.exists():
        return jsonify({"themes": [], "generated_at": None})
    try:
        radar = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"themes": [], "generated_at": None})
    decisions = sw_decisions.load_decisions(ws_dir())
    for t in radar.get("themes") or []:
        d = sw_decisions.decision_for(t.get("title", ""), decisions)
        t["decision"] = d.get("status") if d else None
        t["decision_slug"] = d.get("slug") if d else None
    return jsonify(radar)


@app.route("/api/radar/decide", methods=["POST"])
def api_radar_decide():
    """Approve, skip, or un-decide a theme. The next radar remembers."""
    needs("run")
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    status = (data.get("status") or "").strip().lower()
    if not title:
        return jsonify({"error": "title is required"}), 400
    if status == "clear":
        decisions = sw_decisions.load_decisions(ws_dir())
        decisions.pop(sw_decisions._decision_key(title), None)
        (ws_dir() / "radar_decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"title": title, "status": None})
    if status not in sw_decisions.DECISION_STATUSES:
        return jsonify({"error": "status must be approved, skipped, written or clear"}), 400
    rec = sw_decisions.record_decision(ws_dir(), title, status, note=str(data.get("note") or "")[:300])
    return jsonify(rec)


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
                ws = store().workspace(st.DEFAULT_WORKSPACE)
                _spawn(_radar_cmd(14, OUTPUT_DIR), callback=callback, kind="radar",
                       label="Weekly radar", ws=ws)
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
    needs("run")
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

    upload_dir = system_dir() / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    draft_path = upload_dir / f"{uuid.uuid4().hex}.md"
    draft_path.write_text(draft, encoding="utf-8")

    cmd = [
        sys.executable, str(BASE_DIR / "seo_writer.py"),
        "--audit", str(draft_path),
        "--output-dir", str(ws_dir()),
        "--verify-rounds", str(rounds),
    ]
    if topic:
        cmd.append(topic)
    if intent:
        cmd += ["--intent", intent]
    if apply_fixes:
        cmd.append("--apply")

    audit("audit.started", target=topic or "pasted draft", detail={"rounds": rounds})
    return jsonify({"job_id": _spawn(cmd, kind="audit", label=topic or "Draft evaluation")})


@app.route("/api/reviews")
def api_reviews():
    return jsonify(list_reviews())


def list_reviews() -> list[dict]:
    """Every verification report on disk, newest first."""
    folder = ws_dir()
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted(folder.glob("*_review.json"),
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
    path = ws_dir() / f"{Path(slug).name}_video.md"
    if not path.exists():
        return render_template("deck.html", beats=None, slug=slug), 404
    beats = parse_video_script(path.read_text(encoding="utf-8"))
    return render_template("deck.html", beats=beats, slug=slug)


@app.route("/review/<slug>")
def review_page(slug):
    path = ws_dir() / f"{Path(slug).name}_review.json"
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
    """EventSource endpoint - streams log lines then a done/failed event.

    The log lives on disk, so a reconnect (EventSource sends Last-Event-ID, the
    byte offset of the last line it saw) picks up exactly where it left off,
    even after the server restarted."""
    job = store().job(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    if not store().role_in(g.user, _ws_by_id(job["workspace_id"])):
        return jsonify({"error": "job not found"}), 404
    try:
        start = max(0, int(request.headers.get("Last-Event-ID") or 0))
    except ValueError:
        start = 0
    log_path = _job_log(job_id)

    def stream():
        # "error" is a reserved EventSource event name: the browser fires it on
        # any connection failure, with no data attached. Pipeline failures are
        # sent as "failed" so the two never arrive at the same handler.
        pos, idle, said_queued = start, 0.0, None
        while True:
            chunk = b""
            if log_path.exists():
                with open(log_path, "rb") as f:
                    f.seek(pos)
                    chunk = f.read(65536)
            if chunk and b"\n" in chunk:
                complete = chunk[:chunk.rindex(b"\n") + 1]
                for raw in complete.splitlines(keepends=True):
                    pos += len(raw)
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    yield f"id: {pos}\nevent: log\ndata: {json.dumps({'line': line})}\n\n"
                idle = 0.0
                continue

            current = store().job(job_id) or {}
            status = current.get("status")
            if status == "queued":
                ahead = store().queue_position(job_id)
                if ahead != said_queued:
                    said_queued = ahead
                    note = ("Queued - another job in this workspace is running; this one starts next."
                            if ahead == 0 else f"Queued behind {ahead} other job(s).")
                    yield f"event: log\ndata: {json.dumps({'line': note})}\n\n"
            elif status == "done":
                yield f"event: done\ndata: {json.dumps(current.get('result') or {})}\n\n"
                return
            elif status in ("failed", "interrupted"):
                message = current.get("error") or "The job did not finish."
                yield f"event: failed\ndata: {json.dumps({'message': message})}\n\n"
                return

            time.sleep(0.5)
            idle += 0.5
            if status == "running" and idle >= SILENCE_LIMIT_SECS:
                minutes = SILENCE_LIMIT_SECS // 60
                yield ("event: failed\ndata: "
                       + json.dumps({"message": f"The pipeline stopped responding after {minutes} minutes."})
                       + "\n\n")
                return
            if idle % HEARTBEAT_SECS == 0:
                # Keep the browser and Fly's edge proxy from closing a quiet stream.
                yield ": keepalive\n\n"

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
