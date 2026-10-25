"""
The app's own records: people, client workspaces, who may do what, where each
article stands, what was said about it, and what happened when.

One SQLite file on the Fly volume. A single machine runs the app, so SQLite in
WAL mode is enough, and it keeps the deploy free of a second service. Every
call opens its own short-lived connection: the web threads and the job workers
never share a handle.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

# What each role may do inside one workspace. A reviewer is the client's own
# sign-off: they read, comment, approve or send back, and never spend money.
ROLES = ("owner", "editor", "writer", "reviewer")
ROLE_LABELS = {
    "owner": "Owner",
    "editor": "Editor",
    "writer": "Writer",
    "reviewer": "Client reviewer",
}
CAPABILITIES = {
    "view":    {"owner", "editor", "writer", "reviewer"},
    "comment": {"owner", "editor", "writer", "reviewer"},
    "run":     {"owner", "editor", "writer"},
    "submit":  {"owner", "editor", "writer"},
    "approve": {"owner", "editor", "reviewer"},
    "publish": {"owner", "editor"},
    "manage":  {"owner"},
}

# An article moves forward through these; "changes" sends it back to the writer.
STATUSES = ("draft", "in_review", "changes", "approved", "published")
STATUS_LABELS = {
    "draft": "Draft",
    "in_review": "In review",
    "changes": "Changes requested",
    "approved": "Approved",
    "published": "Published",
}
# Which capability each move needs, and from which states it is allowed.
TRANSITIONS = {
    "in_review": ("submit",  {"draft", "changes"}),
    "changes":   ("approve", {"in_review", "approved"}),
    "approved":  ("approve", {"in_review"}),
    "draft":     ("submit",  {"in_review", "changes", "approved"}),
    "published": ("publish", {"approved", "published"}),
}

DEFAULT_WORKSPACE = "default"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL DEFAULT '',
    pw_hash     TEXT NOT NULL,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    bootstrap   INTEGER NOT NULL DEFAULT 0,
    disabled    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    settings    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role         TEXT NOT NULL,
    PRIMARY KEY (user_id, workspace_id)
);
CREATE TABLE IF NOT EXISTS articles (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    slug         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',
    updated_at   TEXT NOT NULL,
    updated_by   TEXT NOT NULL DEFAULT '',
    wp_post_id   INTEGER,
    wp_link      TEXT,
    PRIMARY KEY (workspace_id, slug)
);
CREATE TABLE IF NOT EXISTS comments (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    slug         TEXT NOT NULL,
    username     TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'comment',
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_by_article ON comments (workspace_id, slug);
CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY,
    at           TEXT NOT NULL,
    username     TEXT NOT NULL DEFAULT '',
    workspace_id INTEGER,
    action       TEXT NOT NULL,
    target       TEXT NOT NULL DEFAULT '',
    detail       TEXT NOT NULL DEFAULT '{}',
    ip           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_by_workspace ON audit (workspace_id, id);
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    cmd          TEXT NOT NULL,
    status       TEXT NOT NULL,
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    error        TEXT,
    result       TEXT NOT NULL DEFAULT '{}',
    extra        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs (status, created_at);
CREATE TABLE IF NOT EXISTS secrets (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    value        TEXT NOT NULL,
    PRIMARY KEY (workspace_id, name)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40] or "workspace"


class Store:
    def __init__(self, path: Path, secret_key: str = ""):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._secret_key = secret_key
        self._init_lock = threading.Lock()
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
        self.ensure_default_workspace()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
        finally:
            c.close()

    # -- users ---------------------------------------------------------------

    def ensure_bootstrap_admin(self, username: str, password: str) -> dict:
        """The APP_USERNAME / APP_PASSWORD account. The environment stays its
        source of truth, so rotating the Fly secret rotates this password."""
        username = (username or "admin").strip()
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE bootstrap = 1").fetchone()
            if row is None:
                row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                c.execute("INSERT INTO users (username, name, pw_hash, is_admin, bootstrap, created_at) "
                          "VALUES (?, ?, ?, 1, 1, ?)",
                          (username, username, generate_password_hash(password), now()))
            else:
                updates = {"bootstrap": 1, "is_admin": 1, "disabled": 0, "username": username}
                if not check_password_hash(row["pw_hash"], password):
                    updates["pw_hash"] = generate_password_hash(password)
                sets = ", ".join(f"{k} = ?" for k in updates)
                c.execute(f"UPDATE users SET {sets} WHERE id = ?", (*updates.values(), row["id"]))
        return self.user_by_name(username)

    def create_user(self, username: str, password: str, name: str = "",
                    is_admin: bool = False) -> dict:
        username = (username or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._@+-]{2,80}", username):
            raise ValueError("Use 2-80 letters, numbers, dots, dashes or an email address.")
        if len(password or "") < 10:
            raise ValueError("Passwords need at least 10 characters.")
        with self._conn() as c:
            try:
                c.execute("INSERT INTO users (username, name, pw_hash, is_admin, created_at) "
                          "VALUES (?, ?, ?, ?, ?)",
                          (username, name.strip() or username, generate_password_hash(password),
                           int(is_admin), now()))
            except sqlite3.IntegrityError:
                raise ValueError(f"{username} already has an account.")
        return self.user_by_name(username)

    def user_by_name(self, username: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
        return dict(row) if row else None

    def user_by_id(self, user_id) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def check_login(self, username: str, password: str) -> dict | None:
        user = self.user_by_name(username)
        if not user or user["disabled"]:
            # Spend the same time on a missing user as on a wrong password.
            check_password_hash(generate_password_hash("x"), password or "")
            return None
        return user if check_password_hash(user["pw_hash"], password or "") else None

    def set_password(self, user_id: int, password: str):
        if len(password or "") < 10:
            raise ValueError("Passwords need at least 10 characters.")
        with self._conn() as c:
            c.execute("UPDATE users SET pw_hash = ? WHERE id = ?",
                      (generate_password_hash(password), user_id))

    def set_disabled(self, user_id: int, disabled: bool):
        with self._conn() as c:
            c.execute("UPDATE users SET disabled = ? WHERE id = ? AND bootstrap = 0",
                      (int(disabled), user_id))

    def any_users(self) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    # -- workspaces ----------------------------------------------------------

    def ensure_default_workspace(self):
        with self._init_lock, self._conn() as c:
            if c.execute("SELECT 1 FROM workspaces WHERE slug = ?", (DEFAULT_WORKSPACE,)).fetchone():
                return
            c.execute("INSERT INTO workspaces (slug, name, settings, created_at) VALUES (?, ?, '{}', ?)",
                      (DEFAULT_WORKSPACE, "My studio", now()))

    def create_workspace(self, name: str, settings: dict | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("A workspace needs a name.")
        base = slugify(name)
        if base == DEFAULT_WORKSPACE:
            base = "client-default"
        with self._conn() as c:
            slug, n = base, 2
            while c.execute("SELECT 1 FROM workspaces WHERE slug = ?", (slug,)).fetchone():
                slug, n = f"{base}-{n}", n + 1
            c.execute("INSERT INTO workspaces (slug, name, settings, created_at) VALUES (?, ?, ?, ?)",
                      (slug, name[:120], json.dumps(settings or {}), now()))
        return self.workspace(slug)

    def workspace(self, slug: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        return self._ws(row)

    def workspace_by_id(self, ws_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
        return self._ws(row)

    @staticmethod
    def _ws(row) -> dict | None:
        if row is None:
            return None
        ws = dict(row)
        try:
            ws["settings"] = json.loads(ws.get("settings") or "{}")
        except ValueError:
            ws["settings"] = {}
        return ws

    def all_workspaces(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM workspaces ORDER BY slug != ?, name COLLATE NOCASE",
                             (DEFAULT_WORKSPACE,)).fetchall()
        return [self._ws(r) for r in rows]

    def update_workspace(self, slug: str, name: str | None = None, settings: dict | None = None):
        ws = self.workspace(slug)
        if not ws:
            raise ValueError("No such workspace.")
        merged = {**ws["settings"], **(settings or {})}
        with self._conn() as c:
            c.execute("UPDATE workspaces SET name = ?, settings = ? WHERE id = ?",
                      ((name or ws["name"]).strip()[:120], json.dumps(merged), ws["id"]))
        return self.workspace(slug)

    def delete_workspace(self, slug: str):
        if slug == DEFAULT_WORKSPACE:
            raise ValueError("The default workspace cannot be deleted.")
        with self._conn() as c:
            c.execute("DELETE FROM workspaces WHERE slug = ?", (slug,))

    # -- membership ----------------------------------------------------------

    def set_role(self, user_id: int, ws_id: int, role: str | None):
        with self._conn() as c:
            if not role:
                c.execute("DELETE FROM members WHERE user_id = ? AND workspace_id = ?", (user_id, ws_id))
                return
            if role not in ROLES:
                raise ValueError(f"Role must be one of {', '.join(ROLES)}.")
            c.execute("INSERT INTO members (user_id, workspace_id, role) VALUES (?, ?, ?) "
                      "ON CONFLICT (user_id, workspace_id) DO UPDATE SET role = excluded.role",
                      (user_id, ws_id, role))

    def role_in(self, user: dict | None, ws: dict) -> str | None:
        """None for no access. A platform admin is owner everywhere."""
        if user is None:
            return None
        if user.get("is_admin"):
            return "owner"
        with self._conn() as c:
            row = c.execute("SELECT role FROM members WHERE user_id = ? AND workspace_id = ?",
                            (user["id"], ws["id"])).fetchone()
        return row["role"] if row else None

    def workspaces_for(self, user: dict) -> list[dict]:
        if user.get("is_admin"):
            return self.all_workspaces()
        with self._conn() as c:
            rows = c.execute(
                "SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id = w.id "
                "WHERE m.user_id = ? ORDER BY w.name COLLATE NOCASE", (user["id"],)).fetchall()
        return [self._ws(r) for r in rows]

    def members(self, ws_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT u.id, u.username, u.name, u.disabled, u.is_admin, m.role FROM members m "
                "JOIN users u ON u.id = m.user_id WHERE m.workspace_id = ? "
                "ORDER BY u.username COLLATE NOCASE", (ws_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- article status and comments -----------------------------------------

    def article_states(self, ws_id: int) -> dict[str, dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM articles WHERE workspace_id = ?", (ws_id,)).fetchall()
        return {r["slug"]: dict(r) for r in rows}

    def article_state(self, ws_id: int, slug: str) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT * FROM articles WHERE workspace_id = ? AND slug = ?",
                            (ws_id, slug)).fetchone()
        return dict(row) if row else {"workspace_id": ws_id, "slug": slug, "status": "draft",
                                      "updated_at": "", "updated_by": "", "wp_post_id": None,
                                      "wp_link": None}

    def set_status(self, ws_id: int, slug: str, status: str, username: str):
        if status not in STATUSES:
            raise ValueError("Unknown status.")
        with self._conn() as c:
            c.execute("INSERT INTO articles (workspace_id, slug, status, updated_at, updated_by) "
                      "VALUES (?, ?, ?, ?, ?) ON CONFLICT (workspace_id, slug) DO UPDATE SET "
                      "status = excluded.status, updated_at = excluded.updated_at, "
                      "updated_by = excluded.updated_by",
                      (ws_id, slug, status, now(), username))

    def set_wordpress(self, ws_id: int, slug: str, post_id: int, link: str):
        self.article_state(ws_id, slug)
        with self._conn() as c:
            c.execute("INSERT INTO articles (workspace_id, slug, status, updated_at, wp_post_id, wp_link) "
                      "VALUES (?, ?, 'draft', ?, ?, ?) ON CONFLICT (workspace_id, slug) DO UPDATE SET "
                      "wp_post_id = excluded.wp_post_id, wp_link = excluded.wp_link",
                      (ws_id, slug, now(), post_id, link))

    def add_comment(self, ws_id: int, slug: str, username: str, body: str,
                    kind: str = "comment") -> dict:
        body = (body or "").strip()[:5000]
        if not body:
            raise ValueError("Write something first.")
        with self._conn() as c:
            cur = c.execute("INSERT INTO comments (workspace_id, slug, username, kind, body, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (ws_id, slug, username, kind, body, now()))
            row = c.execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def comments(self, ws_id: int, slug: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM comments WHERE workspace_id = ? AND slug = ? ORDER BY id",
                             (ws_id, slug)).fetchall()
        return [dict(r) for r in rows]

    def forget_article(self, ws_id: int, slug: str):
        with self._conn() as c:
            c.execute("DELETE FROM articles WHERE workspace_id = ? AND slug = ?", (ws_id, slug))
            c.execute("DELETE FROM comments WHERE workspace_id = ? AND slug = ?", (ws_id, slug))

    # -- audit log -----------------------------------------------------------

    def audit(self, action: str, username: str = "", ws_id: int | None = None,
              target: str = "", detail: dict | None = None, ip: str = ""):
        with self._conn() as c:
            c.execute("INSERT INTO audit (at, username, workspace_id, action, target, detail, ip) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (now(), username or "", ws_id, action, (target or "")[:300],
                       json.dumps(detail or {}, ensure_ascii=False)[:4000], ip or ""))

    def audit_log(self, ws_id: int | None = None, limit: int = 300) -> list[dict]:
        with self._conn() as c:
            if ws_id is None:
                rows = c.execute("SELECT a.*, w.name AS workspace FROM audit a "
                                 "LEFT JOIN workspaces w ON w.id = a.workspace_id "
                                 "ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = c.execute("SELECT a.*, w.name AS workspace FROM audit a "
                                 "LEFT JOIN workspaces w ON w.id = a.workspace_id "
                                 "WHERE a.workspace_id = ? ORDER BY a.id DESC LIMIT ?",
                                 (ws_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["detail"] = json.loads(d["detail"] or "{}")
            except ValueError:
                d["detail"] = {}
            out.append(d)
        return out

    # -- jobs ----------------------------------------------------------------

    def add_job(self, job_id: str, ws_id: int, kind: str, label: str, cmd: list,
                created_by: str, extra: dict | None = None):
        with self._conn() as c:
            c.execute("INSERT INTO jobs (id, workspace_id, kind, label, cmd, status, created_by, "
                      "created_at, extra) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                      (job_id, ws_id, kind, label[:200], json.dumps(cmd), created_by, now(),
                       json.dumps(extra or {})))

    def job(self, job_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row)

    @staticmethod
    def _job(row) -> dict | None:
        if row is None:
            return None
        j = dict(row)
        for key in ("cmd", "result", "extra"):
            try:
                j[key] = json.loads(j[key] or ("[]" if key == "cmd" else "{}"))
            except ValueError:
                j[key] = [] if key == "cmd" else {}
        return j

    def claim_next_job(self) -> dict | None:
        """Atomically move the oldest queued job to running. One job runs per
        workspace at a time - two pipelines in one folder would mistake each
        other's files - while different clients run side by side."""
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM jobs WHERE status = 'queued' AND workspace_id NOT IN "
                            "(SELECT workspace_id FROM jobs WHERE status = 'running') "
                            "ORDER BY created_at, rowid LIMIT 1").fetchone()
            if row is None:
                c.execute("COMMIT")
                return None
            c.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                      (now(), row["id"]))
            c.execute("COMMIT")
        return self.job(row["id"])

    def finish_job(self, job_id: str, status: str, error: str = "", result: dict | None = None):
        with self._conn() as c:
            c.execute("UPDATE jobs SET status = ?, finished_at = ?, error = ?, result = ? WHERE id = ?",
                      (status, now(), error or None, json.dumps(result or {}), job_id))

    def interrupt_running_jobs(self) -> int:
        """Jobs that were running when the machine stopped. They are not re-run
        on their own: a rerun spends money, so a person decides."""
        with self._conn() as c:
            cur = c.execute("UPDATE jobs SET status = 'interrupted', finished_at = ?, "
                            "error = 'The server restarted while this was running.' "
                            "WHERE status = 'running'", (now(),))
            return cur.rowcount

    def requeue_job(self, job_id: str):
        with self._conn() as c:
            c.execute("UPDATE jobs SET status = 'queued', started_at = NULL, finished_at = NULL, "
                      "error = NULL WHERE id = ? AND status IN ('interrupted', 'failed')", (job_id,))

    def jobs(self, ws_id: int | None = None, limit: int = 50, statuses=None) -> list[dict]:
        sql, args = "SELECT * FROM jobs WHERE 1 = 1", []
        if ws_id is not None:
            sql += " AND workspace_id = ?"
            args.append(ws_id)
        if statuses:
            sql += f" AND status IN ({', '.join('?' for _ in statuses)})"
            args += list(statuses)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [self._job(r) for r in rows]

    def queue_position(self, job_id: str) -> int:
        with self._conn() as c:
            row = c.execute("SELECT created_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return 0
            return c.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND created_at < ?",
                             (row["created_at"],)).fetchone()[0]

    # -- secrets (a client's WordPress application password) -----------------

    def _fernet(self):
        from cryptography.fernet import Fernet
        key = hashlib.sha256(("humanly-secrets-v1:" + self._secret_key).encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def set_secret(self, ws_id: int, name: str, value: str):
        with self._conn() as c:
            if not value:
                c.execute("DELETE FROM secrets WHERE workspace_id = ? AND name = ?", (ws_id, name))
                return
            token = self._fernet().encrypt(value.encode()).decode()
            c.execute("INSERT INTO secrets (workspace_id, name, value) VALUES (?, ?, ?) "
                      "ON CONFLICT (workspace_id, name) DO UPDATE SET value = excluded.value",
                      (ws_id, name, token))

    def get_secret(self, ws_id: int, name: str) -> str:
        with self._conn() as c:
            row = c.execute("SELECT value FROM secrets WHERE workspace_id = ? AND name = ?",
                            (ws_id, name)).fetchone()
        if not row:
            return ""
        try:
            return self._fernet().decrypt(row["value"].encode()).decode()
        except Exception:
            # The signing key changed since it was stored: treat it as unset.
            return ""

    def has_secret(self, ws_id: int, name: str) -> bool:
        return bool(self.get_secret(ws_id, name))


def new_token(n: int = 18) -> str:
    return secrets.token_urlsafe(n)
