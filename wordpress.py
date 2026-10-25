"""
Send a finished article to a client's WordPress site.

Uses the REST API that every WordPress since 5.6 ships, authenticated with an
application password (Users -> Profile -> Application Passwords): no plugin to
install on the client's side, and the password can be revoked there at any time.

What arrives in WordPress:
  - a post (draft, pending review, or published - the workspace decides) with
    the article body, its title, slug and meta description as the excerpt
  - the diagrams uploaded to the media library and shown as images, because
    WordPress strips inline SVG for most roles
  - the first diagram as the featured image
Sending again updates the same post rather than creating a second one.
"""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path

import requests

from site_intake import BlockedURL, _check_public

TIMEOUT = 30
POST_STATUSES = ("draft", "pending", "publish")


class WordPressError(RuntimeError):
    """A failure already phrased for the person who clicked the button."""


class WordPress:
    def __init__(self, site_url: str, username: str, app_password: str, session=None):
        self.site = (site_url or "").strip().rstrip("/")
        if not re.match(r"^https?://", self.site):
            self.site = "https://" + self.site if self.site else ""
        self.api = f"{self.site}/wp-json/wp/v2"
        self.session = session or requests.Session()
        # Application passwords are shown with spaces; WordPress accepts either.
        self.auth = (username or "", (app_password or "").replace(" ", ""))

    def _call(self, method: str, path: str, **kw):
        if not self.site or not self.auth[0] or not self.auth[1]:
            raise WordPressError("WordPress is not set up: add the site, a username and an "
                                 "application password in Settings.")
        url = path if path.startswith("http") else self.api + path
        try:
            _check_public(url)
        except BlockedURL as e:
            raise WordPressError(f"Refusing to connect: {e}.")
        try:
            r = self.session.request(method, url, auth=self.auth, timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise WordPressError(f"Could not reach {self.site}: {e.__class__.__name__}.") from e
        if r.status_code in (401, 403):
            raise WordPressError("WordPress refused the login. Check the username and the "
                                 "application password, and that the user can publish posts.")
        if r.status_code == 404 and "/wp-json/" in url:
            raise WordPressError(f"{self.site} has no WordPress REST API at /wp-json/. Is it a "
                                 "WordPress site, and is the REST API enabled?")
        if r.status_code >= 400:
            try:
                detail = r.json().get("message") or r.text[:200]
            except ValueError:
                detail = r.text[:200]
            raise WordPressError(f"WordPress answered {r.status_code}: {detail}")
        try:
            return r.json()
        except ValueError:
            raise WordPressError("WordPress sent back something that is not JSON. A security "
                                 "plugin or a login wall may be in the way.")

    def whoami(self) -> dict:
        me = self._call("GET", "/users/me", params={"context": "edit"})
        caps = me.get("capabilities") or {}
        return {"name": me.get("name") or me.get("slug") or "",
                "can_publish": bool(caps.get("publish_posts")),
                "can_upload": bool(caps.get("upload_files"))}

    def upload(self, path: Path, alt: str = "") -> dict:
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        media = self._call("POST", "/media", data=path.read_bytes(), headers={
            "Content-Disposition": f'attachment; filename="{path.name}"',
            "Content-Type": ctype,
        })
        if alt and media.get("id"):
            try:
                self._call("POST", f"/media/{media['id']}", json={"alt_text": alt[:250]})
            except WordPressError:
                pass  # the image is there; a missing alt text is not worth failing for
        return {"id": media.get("id"), "url": media.get("source_url") or ""}

    def save_post(self, post: dict, post_id: int | None = None) -> dict:
        if post_id:
            try:
                saved = self._call("POST", f"/posts/{post_id}", json=post)
            except WordPressError as e:
                if "404" not in str(e) and "Invalid post ID" not in str(e):
                    raise
                saved = self._call("POST", "/posts", json=post)   # deleted on their side
        else:
            saved = self._call("POST", "/posts", json=post)
        return {"id": saved.get("id"), "link": saved.get("link") or "",
                "status": saved.get("status") or post.get("status")}


def article_body(html: str) -> str:
    """The article as WordPress content: the <body> without its <h1> (WordPress
    prints the title itself) and without script tags (stripped there anyway)."""
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    body = m.group(1) if m else html
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.S | re.I)
    body = re.sub(r"<h1\b[^>]*>.*?</h1>", "", body, count=1, flags=re.S | re.I)
    return body.strip()


def swap_diagrams(body: str, uploaded: list[dict]) -> str:
    """Replace each inline-SVG diagram, in order, with its uploaded image."""
    queue = list(uploaded)

    def repl(m):
        if not queue:
            return m.group(0)
        img = queue.pop(0)
        caption = re.search(r"<figcaption[^>]*>.*?</figcaption>", m.group(0), re.S | re.I)
        alt = img.get("alt", "").replace('"', "&quot;")
        return (f'<figure class="wp-block-image diagram"><img src="{img["url"]}" alt="{alt}"/>'
                f'{caption.group(0) if caption else ""}</figure>')

    return re.sub(r'<figure class="diagram">.*?</figure>', repl, body, flags=re.S | re.I)


def publish_article(wp: WordPress, out: Path, slug: str, status: str = "draft",
                    post_id: int | None = None, category_id: int | None = None,
                    media_cache: dict | None = None) -> dict:
    """Upload the diagrams, then create or update the post. Returns {id, link, status}.

    `media_cache` ({file name: {id, url, size}}) is updated in place: a diagram
    already in their media library is not uploaded a second time."""
    media_cache = media_cache if media_cache is not None else {}
    if status not in POST_STATUSES:
        status = "draft"
    html_files = sorted(out.glob(f"{slug}*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not html_files:
        raise WordPressError("This article has no HTML yet. Open it and save once to rebuild it.")
    try:
        meta = json.loads((out / f"{slug}_meta.json").read_text(encoding="utf-8")).get("seo_meta") or {}
    except (OSError, ValueError):
        meta = {}
    body = article_body(html_files[0].read_text(encoding="utf-8"))

    uploaded = []
    for png in sorted(out.glob(f"{slug}_diagram_*.png")):
        size = png.stat().st_size
        cached = media_cache.get(png.name)
        if cached and cached.get("size") == size and cached.get("id"):
            media = {"id": cached["id"], "url": cached["url"]}
        else:
            media = wp.upload(png, alt=f"Diagram: {meta.get('title') or slug}")
            media_cache[png.name] = {**media, "size": size}
        uploaded.append({**media, "alt": f"Diagram for {meta.get('title') or slug}"})
    body = swap_diagrams(body, uploaded)

    post = {
        "title": meta.get("title") or slug.replace("-", " ").title(),
        "content": body,
        "excerpt": meta.get("description") or "",
        "slug": slug,
        "status": status,
    }
    if uploaded and uploaded[0].get("id"):
        post["featured_media"] = uploaded[0]["id"]
    if category_id:
        post["categories"] = [category_id]
    return wp.save_post(post, post_id=post_id)
