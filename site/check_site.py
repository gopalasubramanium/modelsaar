#!/usr/bin/env python3
"""Static checks for the built site (run after `python site/build.py`).

    python site/check_site.py [site/dist]

Checks: every internal link and asset resolves; exactly one <h1>, a <title>, a description and a
canonical on every page; JSON-LD parses; the sitemap lists every indexable page and only those; robots
and 404 exist; no placeholder text; the installer embeds the pinned SHA and passes `sh -n`; the
commands the pages show match site/facts.py; the CLI commands mentioned in copy exist in the real CLI.
Exit 1 on any failure. This is the durable regression check for the website.
"""

from __future__ import annotations

import html as _html
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import facts  # noqa: E402

DIST = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site/dist"
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


class Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.assets: list[str] = []
        self.h1 = 0
        self.title = ""
        self.in_title = False
        self.desc = False
        self.canonical = ""
        self.jsonld: list[str] = []
        self._in_ld = False
        self._buf = ""
        self.imgs_without_alt = 0

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in ("img", "script", "link") and (a.get("src") or a.get("href")):
            if tag == "link" and a.get("rel") == "canonical":
                self.canonical = a["href"]
            elif tag == "link" and a.get("rel") in ("stylesheet", "icon", "apple-touch-icon", "preload", "sitemap"):
                self.assets.append(a["href"])
            elif tag != "link":
                self.assets.append(a.get("src") or a.get("href"))
        if tag == "img" and "alt" not in a:
            self.imgs_without_alt += 1
        if tag == "h1":
            self.h1 += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta" and a.get("name") == "description" and a.get("content"):
            self.desc = True
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
            self._buf = ""

    def handle_endtag(self, tag):  # type: ignore[no-untyped-def]
        if tag == "title":
            self.in_title = False
        if tag == "script" and self._in_ld:
            self.jsonld.append(self._buf)
            self._in_ld = False

    def handle_data(self, data):  # type: ignore[no-untyped-def]
        if self.in_title:
            self.title += data
        if self._in_ld:
            self._buf += data


def resolve(href: str, page: Path) -> Path | None:
    href = href.split("#", 1)[0].split("?", 1)[0]
    if not href or href.startswith(("http:", "https:", "mailto:")):
        return None
    if href.startswith("/"):
        p = DIST / href.lstrip("/")
    else:
        p = page.parent / href
    if href.endswith("/"):
        p = p / "index.html"
    return p


pages = sorted(DIST.rglob("*.html"))
if not pages:
    err(f"no pages in {DIST}")
site_paths: set[str] = set()
for page in pages:
    text = page.read_text(encoding="utf-8")
    rel = "/" + str(page.relative_to(DIST)).replace("index.html", "")
    site_paths.add(rel)
    s = Scan()
    s.feed(text)
    if s.h1 != 1:
        err(f"{rel}: {s.h1} <h1> elements (want 1)")
    if not s.title.strip():
        err(f"{rel}: missing <title>")
    if not s.desc:
        err(f"{rel}: missing meta description")
    if not s.canonical.startswith(facts.REPO_URL.split("//")[0] + "//"):
        err(f"{rel}: canonical not absolute ({s.canonical!r})")
    if "TODO" in text or re.search(r"\{\{\s", text):
        err(f"{rel}: placeholder text left in page")
    # The public site must not expose the owner's inference host or any key: Tailscale CGNAT addresses
    # (100.64.0.0/10), LAN addresses and ModelSaar/OpenAI-style key literals are refused.
    leak = re.search(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b|\b(192\.168|10)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|\b(ms|sk)-[A-Za-z0-9]{24,}", text)
    if leak:
        err(f"{rel}: private host address or key literal in page ({leak.group(0)})")
    if s.imgs_without_alt:
        err(f"{rel}: {s.imgs_without_alt} <img> without alt")
    for ld in s.jsonld:
        try:
            json.loads(ld)
        except ValueError as e:
            err(f"{rel}: invalid JSON-LD ({e})")
    for href in s.links + s.assets:
        p = resolve(href, page)
        if p is not None and not p.exists():
            err(f"{rel}: broken link/asset {href}")
    # external links must be absolute http(s) or mailto; relative protocol links are not allowed
    for href in s.links:
        if href.startswith("//"):
            err(f"{rel}: protocol-relative link {href}")

# sitemap / robots / 404
sm = DIST / "sitemap.xml"
if not sm.exists():
    err("sitemap.xml missing")
else:
    try:
        tree = ET.parse(sm)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [u.find("s:loc", ns).text for u in tree.getroot().findall("s:url", ns)]  # type: ignore[union-attr]
        mods = [u.find("s:lastmod", ns) for u in tree.getroot().findall("s:url", ns)]
        if any(m is None or not re.match(r"\d{4}-\d{2}-\d{2}", m.text or "") for m in mods):
            err("sitemap: a url lacks a valid lastmod")
        listed = {loc.replace("https://modelsaar.com", "") for loc in locs}
        indexable = {p for p in site_paths if not p.startswith("/404")}
        if listed != indexable:
            err(f"sitemap mismatch: missing {sorted(indexable - listed)}, extra {sorted(listed - indexable)}")
        if any("/modelsaar/" in loc for loc in locs):
            err("sitemap: contains preview base path")
    except ET.ParseError as e:
        err(f"sitemap.xml invalid: {e}")
if not (DIST / "robots.txt").exists():
    err("robots.txt missing")
if not (DIST / "404.html").exists():
    err("404.html missing")
if not (DIST / "llms.txt").exists():
    err("llms.txt missing")
for asset in ("assets/og.png", "assets/favicon.svg", "assets/site.css", "assets/site.js", "assets/where-it-fits.svg"):
    if not (DIST / asset).exists():
        err(f"asset missing: {asset}")

# installer
inst = DIST / "install.sh"
if not inst.exists():
    err("install.sh missing")
else:
    t = inst.read_text(encoding="utf-8")
    if "__PINNED_SHA__" in t or facts.INSTALL_SHA not in t:
        err("install.sh does not embed the pinned SHA")
    if subprocess.run(["sh", "-n", str(inst)], capture_output=True).returncode != 0:
        err("install.sh fails `sh -n`")
    if not re.fullmatch(r"[0-9a-f]{40}", facts.INSTALL_SHA):
        err("facts.INSTALL_SHA is not a full 40-hex SHA")

# commands shown on pages must be the ones in facts (no drift) and name real CLI subcommands
home = (DIST / "index.html").read_text(encoding="utf-8")
gs = (DIST / "get-started/index.html").read_text(encoding="utf-8")
def shown(c: str, text: str) -> bool:
    return c in text or _html.escape(c) in text


for c in (facts.INSTALL_ONE_LINER, facts.FIRST_USE_CHECK):
    if not shown(c, home) or not shown(c, gs):
        err(f"command not shown on home/get-started: {c}")
if not shown(facts.FIRST_USE, home):
    err(f"command not shown on home: {facts.FIRST_USE}")
for c in facts.install_cmds().values():
    if not shown(c, gs):
        err(f"manual install command not shown on get-started: {c}")
help_out = subprocess.run([sys.executable, "-m", "modelsaar.cli", "--help"], capture_output=True, text=True, cwd=ROOT).stdout
subs = set(re.findall(r"\{([a-z0-9,-]+)\}", help_out)[0].split(",")) if "{" in help_out else set()
mentioned = set(re.findall(r"modelsaar (init|serve|test|doctor|probe|discover|explain|decisions|status|client-config|keys|config|eval|demo|uninstall)\b", home + gs))
for m in mentioned - subs:
    err(f"copy mentions `modelsaar {m}` which the CLI does not have")

if errors:
    print("\n".join(f"FAIL {e}" for e in errors))
    sys.exit(1)
print(f"ok: {len(pages)} pages, sitemap/robots/404/llms.txt present, installer pinned to {facts.INSTALL_SHA[:12]}, {len(mentioned)} CLI subcommands verified")
