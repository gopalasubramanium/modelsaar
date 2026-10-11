#!/usr/bin/env python3
"""Build modelsaar.com — a static site generated from this repository.

    python site/build.py                      # production build -> site/dist  (canonical https://modelsaar.com)
    python site/build.py --preview --base /modelsaar/   # preview build: noindex, served under a path prefix

Design goals: no framework, one CSS file, a few KB of optional JavaScript, every fact that the site
states about the product comes from one place (site/facts.py) or straight from repository files
(docs/*.md, docs/live-runs/.../eval-live.json), so the website cannot drift from the code.

Dependencies: Python 3.10+, `markdown` (pip install markdown).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))
import components  # noqa: E402  (site/components.py)
import facts  # noqa: E402  (site/facts.py)

PRODUCTION_URL = "https://modelsaar.com"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def esc(s: str) -> str:
    return html.escape(s, quote=True)


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def git_lastmod(path: Path) -> str:
    """ISO date of the last commit touching ``path`` (sitemap lastmod); today's date if uncommitted."""
    try:
        out = subprocess.check_output(["git", "log", "-1", "--format=%cs", "--", str(path)], cwd=ROOT, text=True).strip()
        if out:
            return out
    except Exception:  # noqa: BLE001
        pass
    return dt.date.today().isoformat()


def md_to_html(text: str, link_rewrite) -> str:  # type: ignore[no-untyped-def]
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"], extension_configs={"toc": {"permalink": False}})
    out = md.convert(text)
    out = re.sub(r'href="([^"]+)"', lambda m: f'href="{link_rewrite(m.group(1))}"', out)
    return out


# --------------------------------------------------------------------------- #
# page model
# --------------------------------------------------------------------------- #
class Site:
    def __init__(self, base: str, preview: bool, out: Path, relative: bool = False) -> None:
        self.base = base if base.endswith("/") else base + "/"
        self.preview = preview
        self.relative = relative  # rewrite root-relative links to page-relative ones (hosts without a known base path)
        self.out = out
        self.url = PRODUCTION_URL
        self.pages: list[dict] = []
        self.commit = git_commit()
        self.built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    def href(self, path: str) -> str:
        """Site-relative link ('/docs/') -> honours the base prefix."""
        if path.startswith(("http://", "https://", "mailto:", "#")):
            return path
        return self.base.rstrip("/") + path if path.startswith("/") else path

    def abs_url(self, path: str) -> str:
        return self.url.rstrip("/") + path

    # ---- layout -------------------------------------------------------------
    def layout(self, page: dict, body: str) -> str:
        title = page["title"]
        full_title = title if page.get("is_home") else f"{title} · ModelSaar"
        desc = page["description"]
        canonical = self.abs_url(page["path"])
        og_image = self.abs_url("/assets/og.png")
        robots = '<meta name="robots" content="noindex, nofollow">' if self.preview else ""
        nav_items = [
            ("/get-started/", "Get started"),
            ("/how-it-works/", "How it works"),
            ("/integrations/", "Integrations"),
            ("/docs/", "Docs"),
            ("/benchmarks/", "Benchmarks"),
            ("/privacy/", "Privacy"),
            ("/roadmap/", "Roadmap"),
        ]
        nav = "".join(
            f'<li><a href="{self.href(p)}"{" aria-current=\"page\"" if page["path"].startswith(p) else ""}>{esc(t)}</a></li>'
            for p, t in nav_items
        )
        jsonld = page.get("jsonld") or []
        jsonld_html = "".join(f'<script type="application/ld+json">{json.dumps(j, ensure_ascii=False)}</script>' for j in jsonld)
        crumbs = page.get("crumbs")
        crumbs_html = ""
        if crumbs:
            items = "".join(f'<li><a href="{self.href(p)}">{esc(t)}</a></li>' for p, t in crumbs[:-1]) + f"<li aria-current=\"page\">{esc(crumbs[-1][1])}</li>"
            crumbs_html = f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{items}</ol></nav>'
        preview_banner = (
            '<div class="preview-banner" role="status">Preview build — not the published site. Search engines are asked not to index it.</div>'
            if self.preview
            else ""
        )
        return f"""<!doctype html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
{robots}
<meta property="og:type" content="website">
<meta property="og:site_name" content="ModelSaar">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{og_image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="ModelSaar — one address for your local AI">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(full_title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{og_image}">
<meta name="theme-color" content="#0f5c50">
<link rel="icon" href="{self.href('/assets/favicon.svg')}" type="image/svg+xml">
<link rel="icon" href="{self.href('/assets/favicon-32.png')}" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="{self.href('/assets/apple-touch-icon.png')}">
<link rel="sitemap" type="application/xml" href="{self.href('/sitemap.xml')}">
<link rel="preload" href="{self.href('/assets/fonts/ibm-plex-sans-latin-400-normal.woff2')}" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{self.href('/assets/fonts/ibm-plex-sans-latin-600-normal.woff2')}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{self.href('/assets/site.css')}?v={self.commit[:8]}">
{jsonld_html}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{preview_banner}
<header class="top">
  <a class="wordmark" href="{self.href('/')}" aria-label="ModelSaar home">
    <svg class="mark" width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" focusable="false"><path d="M3 6h7l4 8-4 8H3" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/><path d="M14 14h11" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M10 6h5M10 22h5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" opacity=".45"/></svg>
    <span>ModelSaar</span>
  </a>
  <nav class="main-nav" aria-label="Main">
    <ul id="nav-list">{nav}<li><a href="{facts.REPO_URL}" rel="noopener">Source on GitHub</a></li></ul>
  </nav>
</header>
<main id="main" class="{page.get('main_class', '')}">
{crumbs_html}
{body}
</main>
<footer class="foot">
  <div class="foot-grid">
    <div>
      <p><strong>ModelSaar</strong> — one address for your local AI. Apache-2.0 licensed gateway; model weights keep their own licences.</p>
      <p class="small">Site built from <a href="{facts.REPO_URL}/commit/{self.commit}">{self.commit[:12]}</a> on {self.built}. Development preview; no release has been tagged.</p>
    </div>
    <ul class="foot-links">
      <li><a href="{self.href('/get-started/')}">Get started</a></li>
      <li><a href="{self.href('/docs/')}">Documentation</a></li>
      <li><a href="{self.href('/benchmarks/')}">Benchmarks and evidence</a></li>
      <li><a href="{self.href('/privacy/')}">Privacy</a></li>
      <li><a href="{facts.REPO_URL}/issues">Report a problem</a></li>
      <li><a href="{self.href('/llms.txt')}">llms.txt</a></li>
    </ul>
  </div>
</footer>
<script src="{self.href('/assets/site.js')}?v={self.commit[:8]}" defer></script>
</body>
</html>
"""

    # ---- rendering ------------------------------------------------------------
    def add(self, path: str, title: str, description: str, body: str, **kw) -> None:  # type: ignore[no-untyped-def]
        # Scrollable regions must be reachable by keyboard (WCAG 2.1.1): code blocks and wide tables scroll.
        body = body.replace("<pre>", '<pre tabindex="0">').replace('<div class="table-wrap">', '<div class="table-wrap" tabindex="0">')
        if kw.get("main_class") == "docs":
            body = body.replace("<table>", '<table tabindex="0">')
        page = {"path": path, "title": title, "description": description, **kw}
        page["html"] = self.layout(page, body)
        self.pages.append(page)

    def write(self) -> None:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        for p in self.pages:
            target = self.out / p["path"].lstrip("/")
            if p["path"].endswith("/"):
                target = target / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            html_out = p["html"]
            if self.relative:
                depth = p["path"].strip("/").count("/") + (1 if p["path"].strip("/") and p["path"].endswith("/") else 0)
                up = "../" * depth if depth else "./"

                def rel(m: re.Match) -> str:
                    path = m.group(2)
                    if path.endswith("/"):
                        path += "index.html"
                    return f'{m.group(1)}="{up}{path.lstrip("/")}"'

                html_out = re.sub(r'\b(href|src)="(/[^"]*)"', rel, html_out)
            target.write_text(html_out, encoding="utf-8")
        # 404 page as a top-level file (GitHub Pages and Cloudflare Pages both use /404.html)
        shutil.copytree(SITE / "static", self.out, dirs_exist_ok=True)
        inst = self.out / "install.sh"
        inst.write_text(inst.read_text(encoding="utf-8").replace("__PINNED_SHA__", facts.INSTALL_SHA), encoding="utf-8")
        shutil.copytree(SITE / "assets", self.out / "assets", dirs_exist_ok=True)
        self._sitemap()
        self._robots()
        if not self.preview:
            (self.out / "CNAME").write_text("modelsaar.com\n")
        (self.out / ".nojekyll").write_text("")

    def _sitemap(self) -> None:
        urls = []
        for p in self.pages:
            if p.get("noindex") or p["path"].startswith("/404"):
                continue
            urls.append(f"<url><loc>{self.abs_url(p['path'])}</loc><lastmod>{p.get('lastmod', self.built)}</lastmod></url>")
        (self.out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>\n",
            encoding="utf-8",
        )

    def _robots(self) -> None:
        if self.preview:
            txt = "User-agent: *\nDisallow: /\n"
        else:
            txt = f"User-agent: *\nAllow: /\nSitemap: {self.abs_url('/sitemap.xml')}\n"
        (self.out / "robots.txt").write_text(txt)


# --------------------------------------------------------------------------- #
# content
# --------------------------------------------------------------------------- #
def render_fragment(site: Site, name: str, **vars) -> str:  # type: ignore[no-untyped-def]
    """Content fragments are HTML with {{ expr }} placeholders evaluated against facts + vars."""
    text = (SITE / "content" / name).read_text(encoding="utf-8")
    ctx = {"facts": facts, "c": components, "site": site, "esc": esc, "href": site.href, "cmd": components.cmd, **vars}

    def sub(m: re.Match) -> str:
        return str(eval(m.group(1), {}, ctx))  # noqa: S307 - build-time templates authored in this repo

    return re.sub(r"\{\{\s*(.+?)\s*\}\}", sub, text)


DOC_PAGES = [
    # (repo path, site path, title, description)
    ("docs/installation.md", "/docs/installation/", "Installation, upgrade, rollback, uninstall", "Install ModelSaar from source, configure it, run it under Docker Compose, upgrade, roll back and uninstall."),
    ("docs/routing.md", "/docs/routing/", "Routing: requirements, eligibility, ranking", "How ModelSaar analyses a request, which hard filters apply, how candidates are ranked and how embeddings, memory budgets and failover behave."),
    ("docs/architecture.md", "/docs/architecture/", "Architecture", "Components of the ModelSaar gateway and how a request flows through them."),
    ("docs/privacy.md", "/docs/privacy/", "Privacy and security of the gateway", "Defaults and guarantees of the gateway: binding, keys, locality, payload handling, logging, code execution."),
    ("docs/evaluation.md", "/docs/evaluation/", "Evaluation harness", "How `modelsaar eval` compares automatic routing with fixed, rules, random and oracle policies."),
    ("docs/verification-report.md", "/docs/verification-report/", "Verification report", "What was executed, where, with what outcome — including the live runs on real hardware and everything still NOT RUN."),
    ("docs/review-2026-10-11-findings.md", "/docs/review-2026-10-11/", "Independent review findings F01–F18", "Findings of the 2026-10-11 review of commit 1122e1f, their fixes, regression tests and execution evidence."),
    ("docs/troubleshooting.md", "/docs/troubleshooting/", "Troubleshooting", "Common failures when installing or running ModelSaar and what to do about them."),
    ("docs/extending.md", "/docs/extending/", "Extending ModelSaar", "Adding backends, probes and clients."),
    ("docs/roadmap.md", "/docs/roadmap-detail/", "Roadmap (repository)", "Planned work as recorded in the repository."),
    ("docs/clients/open-webui.md", "/docs/clients/open-webui/", "Open WebUI", "Connecting Open WebUI to ModelSaar."),
    ("docs/clients/openclaw.md", "/docs/clients/openclaw/", "OpenClaw", "Connecting OpenClaw to ModelSaar."),
    ("docs/clients/opencode.md", "/docs/clients/opencode/", "OpenCode", "Connecting OpenCode (V1 and V2 config schemas) to ModelSaar."),
    ("docs/clients/hermes.md", "/docs/clients/hermes/", "Hermes Agent", "Connecting NousResearch Hermes Agent to ModelSaar."),
    ("CHANGELOG.md", "/docs/changelog/", "Changelog", "What changed in each ModelSaar revision."),
    ("CONTRIBUTING.md", "/docs/contributing/", "Contributing", "How to report problems, propose changes and run the test suite."),
    ("SECURITY.md", "/docs/security-policy/", "Security policy", "How to report a vulnerability in ModelSaar."),
]


def doc_link_rewriter(site: Site, current_repo_path: str):  # type: ignore[no-untyped-def]
    by_repo = {rp: sp for rp, sp, _, _ in DOC_PAGES}
    cur_dir = Path(current_repo_path).parent

    def rw(url: str) -> str:
        if url.startswith(("http://", "https://", "mailto:")):
            return url
        if url.startswith("#"):
            return url
        target, _, frag = url.partition("#")
        rel = (cur_dir / target).resolve().relative_to(ROOT.resolve()) if target else Path(current_repo_path)
        rel_s = str(rel)
        if rel_s in by_repo:
            return site.href(by_repo[rel_s]) + (f"#{frag}" if frag else "")
        # anything else in the repository: link to GitHub at the built commit
        return f"{facts.REPO_URL}/blob/{site.commit}/{rel_s}" + (f"#{frag}" if frag else "")

    return rw


def build(site: Site) -> None:
    # ---- top-level pages (hand-written fragments) -------------------------------
    site.add("/", "ModelSaar — one address for your local AI", facts.TAGLINE_LONG, render_fragment(site, "home.html"), is_home=True, main_class="home", jsonld=facts.jsonld_home(site.url, site.commit), lastmod=git_lastmod(SITE / "content/home.html"))
    pages = [
        ("/get-started/", "Get started", "Prerequisites, installation, first request and client connection for ModelSaar on macOS, Linux and WSL.", "get-started.html"),
        ("/how-it-works/", "How it works", "How ModelSaar turns a chat request into a routing decision: requirements, hard filters, evidence-based ranking, continuity and the decision record.", "how-it-works.html"),
        ("/integrations/", "Integrations", "Which clients and inference backends ModelSaar supports, and what kind of evidence backs each claim.", "integrations.html"),
        ("/benchmarks/", "Benchmarks and evidence", "Methodology, actual results and limitations of the ModelSaar evaluation, with links to the raw per-request records.", "benchmarks.html"),
        ("/privacy/", "Privacy", "What the ModelSaar gateway does with your requests, and what this website collects (nothing beyond the host's access logs).", "privacy.html"),
        ("/roadmap/", "Roadmap and status", "Current status of ModelSaar and clearly identified future work.", "roadmap.html"),
        ("/docs/", "Documentation", "ModelSaar documentation: installation, configuration, routing, API, operations, evaluation, clients.", "docs-index.html"),
    ]
    for path, title, desc, frag in pages:
        site.add(path, title, desc, render_fragment(site, frag), crumbs=[("/", "Home"), (path, title)], jsonld=facts.jsonld_page(site.url, path, title, desc), lastmod=git_lastmod(SITE / "content" / frag))
    site.add("/404.html", "Page not found", "This page does not exist on modelsaar.com.", render_fragment(site, "404.html"), noindex=True)
    # ---- documentation rendered from the repository -------------------------------
    for repo_path, site_path, title, desc in DOC_PAGES:
        src = ROOT / repo_path
        text = src.read_text(encoding="utf-8")
        text = re.sub(r"^# .*\n", "", text, count=1)  # the page template supplies the H1
        body_html = md_to_html(text, doc_link_rewriter(site, repo_path))
        body = (
            f'<article class="doc"><header class="doc-head"><h1>{esc(title)}</h1>'
            f'<p class="small">Rendered from <a href="{facts.REPO_URL}/blob/{site.commit}/{repo_path}"><code>{repo_path}</code></a> at commit <code>{site.commit[:12]}</code>. '
            f'The repository file is authoritative.</p></header>{body_html}</article>'
        )
        site.add(site_path, title, desc, body, crumbs=[("/", "Home"), ("/docs/", "Docs"), (site_path, title)], main_class="docs", jsonld=facts.jsonld_page(site.url, site_path, title, desc), lastmod=git_lastmod(src))
    # ---- llms.txt ------------------------------------------------------------------
    (SITE / "static").mkdir(exist_ok=True)
    llms = facts.llms_txt(site.url, [(p["path"], p["title"], p["description"]) for p in site.pages if not p.get("noindex")])
    (SITE / "static" / "llms.txt").write_text(llms, encoding="utf-8")
    site.write()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/", help="path prefix the site is served under (preview builds on a project page)")
    ap.add_argument("--preview", action="store_true", help="mark the build noindex and omit CNAME")
    ap.add_argument("--out", default=str(SITE / "dist"))
    ap.add_argument("--relative", action="store_true", help="page-relative links (for a preview host with an unknown base path)")
    a = ap.parse_args()
    site = Site(a.base, a.preview, Path(a.out), relative=a.relative)
    build(site)
    n = len(site.pages)
    print(f"built {n} pages -> {site.out} (base {site.base!r}, preview={site.preview}, commit {site.commit[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
