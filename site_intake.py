#!/usr/bin/env python3
"""
Read a client's website before writing for it.

    python site_intake.py https://www.example.com --out output/workspaces/acme

Writes into --out:
  site_pages.json     every page found: url, title, kind (article/product/other), lastmod
  samples/*.md        two or three of their own articles, the voice to write in
  notes/*.md          their product and solution pages, as research notes with
                      the source URL on top, so product facts come from them
  intake_report.md    what was found, for a person to read

It reads the sitemap (from robots.txt, then the usual places), falls back to the
links on the home page, honours robots.txt, and never fetches a private or
loopback address: the URL comes from a user and the fetch runs on the server.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "HumanlySiteIntake/1.0 (reads a client's site to write for it)"
TIMEOUT = 15
MAX_SITEMAP_URLS = 3000
MAX_TITLES = 160          # pages whose <title> is fetched
SAMPLE_COUNT = 3
NOTE_COUNT = 8
NOTE_MAX_CHARS = 7000
MAX_REDIRECTS = 5

ARTICLE_HINTS = ("/blog/", "/articles/", "/article/", "/news/", "/insights/", "/posts/",
                 "/post/", "/resources/", "/guides/", "/learn/", "/stories/")
PRODUCT_HINTS = ("/product", "/products/", "/solutions/", "/solution/", "/features/",
                 "/platform/", "/pricing", "/use-cases/", "/integrations/", "/services/",
                 "/why-", "/how-it-works", "/docs/", "/documentation/")
SKIP_HINTS = ("/tag/", "/tags/", "/category/", "/categories/", "/author/", "/page/",
              "/feed", "/wp-json", "/cart", "/login", "/signin", "/sign-in", "/privacy",
              "/terms", "/cookie", "/legal", ".pdf", ".jpg", ".png", ".zip")


def log(msg: str):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Fetching, safely
# ---------------------------------------------------------------------------

class BlockedURL(ValueError):
    pass


def _check_public(url: str):
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedURL(f"not an http(s) URL: {url}")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as e:
        raise BlockedURL(f"cannot resolve {parts.hostname}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise BlockedURL(f"{parts.hostname} resolves to a private address")


class Fetcher:
    def __init__(self, root: str):
        self.root = root
        self.host = urlparse(root).hostname
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = RobotFileParser()
        try:
            r = self.get(urljoin(root, "/robots.txt"), check_robots=False)
            self.robots.parse(r.text.splitlines() if r is not None and r.ok else [])
        except Exception:
            self.robots.parse([])

    def allowed(self, url: str) -> bool:
        try:
            return self.robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def get(self, url: str, check_robots: bool = True):
        """GET with every redirect hop checked, so a public URL cannot bounce
        the server into its own network."""
        if check_robots and not self.allowed(url):
            return None
        for _ in range(MAX_REDIRECTS + 1):
            _check_public(url)
            r = self.session.get(url, timeout=TIMEOUT, allow_redirects=False)
            if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, r.headers.get("Location", ""))
                continue
            # With no charset in the header, requests assumes Latin-1 and turns
            # every curly quote into mojibake. The web is UTF-8.
            if "charset" not in r.headers.get("Content-Type", "").lower():
                r.encoding = "utf-8"
            return r
        return None

    def same_site(self, url: str) -> bool:
        h = (urlparse(url).hostname or "").lower()
        base = (self.host or "").lower()
        strip = lambda x: x[4:] if x.startswith("www.") else x  # noqa: E731
        return strip(h) == strip(base)


# ---------------------------------------------------------------------------
# Finding the pages
# ---------------------------------------------------------------------------

def _sitemap_candidates(f: Fetcher) -> list[str]:
    found = []
    try:
        r = f.get(urljoin(f.root, "/robots.txt"), check_robots=False)
        if r is not None and r.ok:
            found += [line.split(":", 1)[1].strip() for line in r.text.splitlines()
                      if line.lower().startswith("sitemap:")]
    except Exception:
        pass
    found += [urljoin(f.root, p) for p in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml")]
    seen, out = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_sitemaps(f: Fetcher) -> list[dict]:
    pages, queue, seen = {}, _sitemap_candidates(f), set()
    while queue and len(pages) < MAX_SITEMAP_URLS and len(seen) < 60:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            r = f.get(url, check_robots=False)
            if r is None or not r.ok or b"<" not in r.content[:200]:
                continue
            root = ET.fromstring(r.content)
        except Exception:
            continue
        kind = _local(root.tag)
        for node in root:
            loc = lastmod = ""
            for child in node:
                if _local(child.tag) == "loc":
                    loc = (child.text or "").strip()
                elif _local(child.tag) == "lastmod":
                    lastmod = (child.text or "").strip()
            if not loc:
                continue
            if kind == "sitemapindex":
                queue.append(loc)
            elif f.same_site(loc):
                pages.setdefault(loc, {"url": loc, "lastmod": lastmod[:10]})
        if pages:
            log(f"  Sitemap {url}: {len(pages)} pages so far")
    return list(pages.values())


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def crawl_home(f: Fetcher) -> list[dict]:
    r = f.get(f.root)
    if r is None or not r.ok:
        return []
    p = _Links()
    p.feed(r.text)
    out = {}
    for href in p.links:
        u = urljoin(f.root, href).split("#")[0]
        if u.startswith("http") and f.same_site(u):
            out.setdefault(u, {"url": u, "lastmod": ""})
    return list(out.values())


def classify(url: str) -> str:
    path = urlparse(url).path.lower() + "/"
    if any(h in path for h in SKIP_HINTS):
        return "skip"
    if any(h in path for h in ARTICLE_HINTS) or re.search(r"/20\d\d/\d\d/", path):
        # The listing page itself (/blog/) is not an article.
        return "article" if path.strip("/").count("/") >= 1 else "other"
    if any(h in path for h in PRODUCT_HINTS):
        return "product"
    return "other"


# ---------------------------------------------------------------------------
# Reading a page
# ---------------------------------------------------------------------------

class _Text(HTMLParser):
    """The readable body of a page: headings, paragraphs and list items, with
    navigation, headers, footers, forms and scripts left out."""
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form",
            "svg", "button", "iframe", "template"}
    BLOCKS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "p": "", "li": "- ",
              "blockquote": "> ", "td": ""}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.title = ""
        self.og_title = ""
        self.in_title = False
        self.block = None
        self.buf = []
        self.out = []
        self.in_main = 0
        self.main_out = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("property") == "og:title":
            self.og_title = a.get("content") or ""
        if tag == "title":
            self.in_title = True
        if tag in self.SKIP:
            self.skip += 1
        if tag in ("article", "main"):
            self.in_main += 1
        if tag in self.BLOCKS and not self.skip:
            self.block, self.buf = tag, []

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == self.block:
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if text and (tag != "p" or len(text) > 30 or self.in_main):
                line = self.BLOCKS[tag] + text
                self.out.append(line)
                if self.in_main:
                    self.main_out.append(line)
            self.block = None
        if tag in ("article", "main") and self.in_main:
            self.in_main -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.block and not self.skip:
            self.buf.append(data)


def read_page(f: Fetcher, url: str) -> dict | None:
    try:
        r = f.get(url)
    except (BlockedURL, requests.RequestException):
        return None
    if r is None or not r.ok or "html" not in r.headers.get("Content-Type", "html"):
        return None
    p = _Text()
    try:
        p.feed(r.text)
    except Exception:
        return None
    lines = p.main_out if len(" ".join(p.main_out)) > 600 else p.out
    title = unescape((p.og_title or p.title or "").strip())
    title = re.split(r"\s+[|–—-]\s+", title)[0].strip() if title else ""
    return {"url": url, "title": title, "text": "\n\n".join(lines)}


def _title_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or urlparse(url).hostname or ""
    return re.sub(r"[-_]+", " ", slug).strip().capitalize()


def _file_slug(url: str) -> str:
    path = urlparse(url).path.strip("/") or "home"
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:70] or "page"


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def run(url: str, out: Path) -> dict:
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
    out.mkdir(parents=True, exist_ok=True)
    log(f"\n{'=' * 60}\nSite intake: {root}\nOutput: {out}\n{'=' * 60}")

    try:
        _check_public(root)
    except BlockedURL as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(2)
    f = Fetcher(root)

    log("[INTAKE 1] Finding their pages (sitemap, then the home page)")
    pages = read_sitemaps(f)
    source = "sitemap"
    if not pages:
        pages = crawl_home(f)
        source = "home page links"
    for p in pages:
        p["kind"] = classify(p["url"])
    pages = [p for p in pages if p["kind"] != "skip"]
    counts = {k: sum(1 for p in pages if p["kind"] == k) for k in ("article", "product", "other")}
    log(f"  {len(pages)} pages from the {source}: {counts['article']} articles, "
        f"{counts['product']} product pages, {counts['other']} other")
    if not pages:
        print("ERROR: no pages found. Check the address, or whether the site blocks crawlers.",
              flush=True)
        sys.exit(3)

    log("[INTAKE 2] Reading titles")
    # Product pages and the newest articles first; the rest as room allows.
    articles = sorted([p for p in pages if p["kind"] == "article"],
                      key=lambda p: p["lastmod"], reverse=True)
    # The overview pages (/pricing, /features/x) before the deep docs (/docs/a/b/c).
    products = sorted([p for p in pages if p["kind"] == "product"],
                      key=lambda p: urlparse(p["url"]).path.strip("/").count("/"))
    others = [p for p in pages if p["kind"] == "other"]
    to_read = (products[:40] + articles[:80] + others)[:MAX_TITLES]
    with ThreadPoolExecutor(max_workers=6) as pool:
        read = {r["url"]: r for r in pool.map(lambda p: read_page(f, p["url"]), to_read) if r}
    for p in pages:
        got = read.get(p["url"])
        p["title"] = (got or {}).get("title") or _title_from_url(p["url"])
        p["words"] = len(((got or {}).get("text") or "").split())
    log(f"  Read {len(read)} pages")

    log("[INTAKE 3] Choosing voice samples from their own articles")
    samples_dir = out / "samples"
    samples_dir.mkdir(exist_ok=True)
    # Some sites keep posts at the root (/my-post/), with no /blog/ to tell them
    # apart; then any long page of prose is a candidate.
    pool_pages = articles or others
    candidates = [read[p["url"]] for p in pool_pages if p["url"] in read
                  and 600 <= len(read[p["url"]]["text"].split()) <= 6000]
    candidates.sort(key=lambda r: -len(r["text"].split()))
    chosen = candidates[:SAMPLE_COUNT]
    for old in samples_dir.glob("site-*.md"):
        old.unlink()
    for r in chosen:
        (samples_dir / f"site-{_file_slug(r['url'])}.md").write_text(
            f"# {r['title']}\n\n{r['text']}\n", encoding="utf-8")
        log(f"  Sample: {r['title']} ({len(r['text'].split())} words)")
    if not chosen:
        log("  No article long enough to learn a voice from. Add samples by hand to "
            f"{samples_dir}, or the writer uses a neutral voice.")

    log("[INTAKE 4] Saving their product pages as research notes")
    notes_dir = out / "notes"
    notes_dir.mkdir(exist_ok=True)
    for old in notes_dir.glob("site-*.md"):
        old.unlink()
    saved = 0
    for p in products:
        r = read.get(p["url"])
        if not r or len(r["text"].split()) < 120:
            continue
        text = r["text"][:NOTE_MAX_CHARS]
        (notes_dir / f"site-{_file_slug(p['url'])}.md").write_text(
            f"# {r['title']}\n\nSource: {p['url']}\n"
            f"Retrieved: {datetime.now(timezone.utc).date().isoformat()} from the client's own site. "
            f"Every statement below comes from this page.\n\n{text}\n", encoding="utf-8")
        saved += 1
        log(f"  Note: {r['title']}")
        if saved >= NOTE_COUNT:
            break

    (out / "site_pages.json").write_text(json.dumps(
        [{k: p.get(k) for k in ("url", "title", "kind", "lastmod", "words")} for p in pages],
        indent=1, ensure_ascii=False), encoding="utf-8")

    report = [f"# Site intake: {root}", "",
              f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC, from the {source}._", "",
              f"- **{len(pages)} pages**: {counts['article']} articles, {counts['product']} product pages, "
              f"{counts['other']} other",
              f"- **Voice samples**: {len(chosen)}", f"- **Product notes**: {saved}", "",
              "## Their newest articles", ""]
    report += [f"- {p['lastmod'] or '        '}  [{p['title']}]({p['url']})" for p in articles[:25]]
    report += ["", "## Product pages", ""]
    report += [f"- [{p['title']}]({p['url']})" for p in products[:40]]
    (out / "intake_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    summary = {"root": root, "source": source, "pages": len(pages), **counts,
               "samples": len(chosen), "notes": saved,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "intake.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"\nDone. {len(pages)} pages, {len(chosen)} voice samples, {saved} product notes.")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    run(args.url, args.out)


if __name__ == "__main__":
    main()
