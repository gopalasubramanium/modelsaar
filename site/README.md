# modelsaar.com — source, build, deployment, rollback

The public website lives in this directory and is generated from the repository, so commands, support
status and benchmark numbers cannot drift from the code.

## Layout

| path | role |
|---|---|
| `build.py` | the generator (Python 3.10+, `markdown` only). `python site/build.py` → `site/dist/` (production: canonical `https://modelsaar.com`, `CNAME`, indexable). `--preview --base /modelsaar/` → noindex, path-prefixed (project-page preview). |
| `facts.py` | **every fact the site states**: repository URL, status, pinned installer commit, commands, support matrix with evidence kinds, structured data, `llms.txt`. Benchmark numbers are read from `docs/live-runs/2026-10-11-gx10-hardening/eval-live.json` at build time. |
| `components.py` | the decision-record walkthrough (illustrative scenarios), command blocks, support matrix, benchmark table |
| `content/*.html` | hand-written page bodies with `{{ … }}` placeholders evaluated against `facts`/`components` |
| `assets/` | one stylesheet, one optional script, self-hosted IBM Plex (OFL), icons, OG image, diagram SVG |
| `static/` | copied verbatim: `install.sh` (pin substituted at build), `_headers` (Cloudflare Pages only), `llms.txt` (generated) |
| `check_site.py` | static regression checks: links/assets, one `<h1>`, title/description/canonical, JSON-LD, sitemap ⟷ pages, robots, 404, installer pin + `sh -n`, commands match `facts.py`, CLI subcommands exist |
| `browser_checks.py` | Playwright checks: console errors, horizontal overflow at 390 px, keyboard focus order, reduced-motion, copy buttons, tabs; axe-core accessibility scan |

Documentation pages under `/docs/` are rendered from `docs/*.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
`SECURITY.md` at the built commit, with Markdown links rewritten to site URLs or to GitHub at that commit.

## Build and check locally

```bash
pip install -e . markdown            # the site imports facts from the package and the CLI
python site/build.py                 # production build
python site/check_site.py            # must print "ok: …"
python -m http.server -d site/dist 8765   # then open http://127.0.0.1:8765/
pip install playwright && playwright install chromium && python site/browser_checks.py http://127.0.0.1:8765
```

## Hosting and deployment (GitHub Pages)

Chosen because it needs no new account or payment and deploys from this repository. The workflow
`.github/workflows/site.yml`:

* on every push to `website/modelsaar-com` (and `main`) builds a **preview** (noindex, base `/modelsaar/`),
  runs the checks and keeps the result as a workflow artifact;
* on **workflow_dispatch** with `target=production` from a chosen ref, builds the production site, runs
  `check_site.py`, verifies the installer's pinned commit is reachable on `origin`, and deploys to the
  `github-pages` environment. The deployed revision is the dispatched ref — recorded in the workflow run.

One-time repository settings (owner, via GitHub UI or `gh`):

```bash
gh api -X POST repos/gopalasubramanium/modelsaar/pages -f build_type=workflow          # enable Pages, source = GitHub Actions
gh api -X PUT  repos/gopalasubramanium/modelsaar/pages -f cname=modelsaar.com -F https_enforced=true   # custom domain, once DNS is set
```

DNS at Cloudflare (the zone already uses Cloudflare nameservers and currently has **no** A/AAAA/CNAME/MX
records, so nothing is displaced). Add, **DNS only** (grey cloud) so GitHub can issue the certificate:

| type | name | value |
|---|---|---|
| A | `modelsaar.com` | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` |
| AAAA | `modelsaar.com` | `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153` |
| CNAME | `www` | `gopalasubramanium.github.io` |

Then in the repository's Pages settings set the custom domain to `modelsaar.com` and tick *Enforce HTTPS*
once the certificate is issued. GitHub redirects `www.modelsaar.com` → `modelsaar.com` and
`https://gopalasubramanium.github.io/modelsaar/` → the custom domain. Optionally verify the domain
under *Settings → Pages → Verified domains* (adds a `_github-pages-challenge-…` TXT record) to prevent takeover.

Until the DNS records exist, the production deployment is reachable only at
`https://gopalasubramanium.github.io/modelsaar/` **and** its absolute links point at modelsaar.com, so for
previewing use the preview build (path-prefixed) from the workflow artifact or a local server.

Headers: GitHub Pages sets its own caching (`max-age=600`) and does not allow custom headers; the
`_headers` file applies only if the site is ever moved to Cloudflare Pages (same repository, same build
command `python site/build.py`, output `site/dist`).

## Rollback

Dispatch the `site` workflow with `target=production` from the previous good commit (the run page of
every production deployment names its ref). Nothing else changes; DNS and settings stay as they are.

## Updating the pinned installer commit

Edit `INSTALL_SHA` in `site/facts.py` (full 40-hex SHA of a commit that is public and whose CI passed),
rebuild, run `check_site.py` (it refuses a non-40-hex value), and deploy. The CI step
"pinned revision is public" fails if the commit is not reachable on `origin`.
