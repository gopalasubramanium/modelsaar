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
| `publish_pages.py` | builds production and commits the output to the `gh-pages` branch (`build`), restores an earlier build (`rollback <commit>`), lists deployments (`log`) |

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

## Hosting and deployment (GitHub Pages, "deploy from a branch")

Chosen because it needs no new account or payment and publishes from this repository. The published
site is the generated-output branch **`gh-pages`**, which contains only the static output plus
`.nojekyll`, `CNAME` (`modelsaar.com`) and `BUILD-INFO.json` (source commit, generator, build time,
sha256 of the output, installer pin). A source branch containing the generator is not the website; only
`gh-pages` is served.

Why not `workflow_dispatch` + `actions/deploy-pages`: GitHub only offers manual dispatch for workflows
that exist on the default branch (`main`), and both source PRs must stay unmerged, so a workflow on the
website branch cannot be dispatched. Branch publishing needs nothing on `main`. `.github/workflows/site.yml`
therefore only builds and checks on push/PR (artifact `site-dist-<sha>`); it never publishes.

### Publish (owner, on a machine with push access)

```bash
git checkout website/modelsaar-com            # the verified website revision (clean tree required)
python site/publish_pages.py build            # builds production, runs check_site.py, commits to gh-pages
python site/publish_pages.py log              # gh-pages history: output commit -> source commit
git push origin gh-pages                      # this is the deployment
```

The Mac launcher `gh/gh_run.command publish` does all of this from the git bundle (see `gh/README.md`),
then configures Pages through the API: source branch `gh-pages`, path `/`, custom domain `modelsaar.com`.
One-time equivalent by hand:

```bash
gh api -X POST repos/gopalasubramanium/modelsaar/pages -f source[branch]=gh-pages -f source[path]=/   # first time
gh api -X PUT  repos/gopalasubramanium/modelsaar/pages -f cname=modelsaar.com                            # custom domain
```

Preview vs production: a repository has exactly one Pages site, so there is no separate preview
destination here; `gh-pages` is production. Previews are the local build (`python site/build.py` then
`python -m http.server -d site/dist`), the CI artifact, and the private Claude preview. A public
noindex preview would still be public (noindex is not access control), so none is published.

### Custom domain — supported sequence

Current DNS state (checked 2026-10-11 via DNS-over-HTTPS): nameservers `aspen.ns.cloudflare.com`,
`moura.ns.cloudflare.com`; no A/AAAA for the apex, `www` NXDOMAIN, no MX; the full zone inventory is
visible only in the Cloudflare dashboard — check it before adding records and keep everything unrelated.

1. **Verify the domain with GitHub** (prevents takeover): `gh/gh_run.command domain-start` prints the
   TXT record GitHub asks for (`_github-pages-challenge-gopalasubramanium.modelsaar.com` → token).
   Add it at Cloudflare (DNS only), then `gh/gh_run.command domain-verify`.
2. **Associate the domain with the Pages site**: done by `publish` (`CNAME` file + API `cname`).
3. **Add the DNS records at Cloudflare**, proxy status *DNS only* (grey cloud) so GitHub can issue the
   certificate:

   | type | name | value |
   |---|---|---|
   | A | `modelsaar.com` | `185.199.108.153` |
   | A | `modelsaar.com` | `185.199.109.153` |
   | A | `modelsaar.com` | `185.199.110.153` |
   | A | `modelsaar.com` | `185.199.111.153` |
   | AAAA | `modelsaar.com` | `2606:50c0:8000::153` |
   | AAAA | `modelsaar.com` | `2606:50c0:8001::153` |
   | AAAA | `modelsaar.com` | `2606:50c0:8002::153` |
   | AAAA | `modelsaar.com` | `2606:50c0:8003::153` |
   | CNAME | `www` | `gopalasubramanium.github.io` |

4. **Verify resolution and the certificate**: `dig +short modelsaar.com A`, `dig +short www.modelsaar.com CNAME`,
   then `gh/gh_run.command status` until `.https_certificate.state` is `approved` (up to 24 h).
5. **Enforce HTTPS and check redirects**: `gh/gh_run.command https` (sets `https_enforced=true`), then
   `curl -sI http://modelsaar.com/` → 301 to https, `curl -sI https://www.modelsaar.com/` → 301 to the apex,
   `curl -sI https://gopalasubramanium.github.io/modelsaar/` → 301 to the apex, `curl -fsS https://modelsaar.com/install.sh | sha256sum` equals the `install.sh` in the served `gh-pages` commit.

Search Console / Bing: after step 5, add the verification meta tag to `site/build.py` (`layout()` head)
or a DNS TXT at Cloudflare, rebuild/publish, submit `https://modelsaar.com/sitemap.xml`.

### Rollback (executable)

`gh-pages` history is the deployment history (`python site/publish_pages.py log`). To restore an earlier
build **as a new commit** (history is never rewritten; no force-push):

```bash
python site/publish_pages.py rollback <gh-pages-commit>   # verifies the commit is on gh-pages and has BUILD-INFO.json
git push origin gh-pages
```

or `gh/gh_run.command rollback <gh-pages-commit>` on the Mac. The restored tree is byte-identical to the
chosen build (`BUILD-INFO.json: output_sha256`). Before any successful production deployment exists, the
recovery action is to unpublish: `gh api -X DELETE repos/gopalasubramanium/modelsaar/pages` (the domain
then answers 404 from GitHub) — `gh/gh_run.command unpublish`.

Headers: GitHub Pages sets its own caching (`max-age=600`) and does not allow custom headers; the
`_headers` file applies only if the site is ever moved to Cloudflare Pages (same repository, build command
`python site/build.py`, output `site/dist`).

## Updating the pinned installer commit

Edit `INSTALL_SHA` in `site/facts.py` (full 40-hex SHA of a commit that is public and whose CI passed),
rebuild, run `check_site.py` (it refuses a non-40-hex value), then `publish_pages.py build` and push. The CI
step "pinned revision must be public" fails if the commit is not reachable on `origin`.
