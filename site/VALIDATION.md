# Validation record — modelsaar.com (website branch)

What was checked, where, and the result. Lab measurements are lab measurements; there is no field data
for a site that is not yet public.

| check | tool / environment | result |
|---|---|---|
| Build | `python site/build.py` (CPython 3.13, markdown 3.11) | 26 pages, 708 KB total; largest asset `og.png` 76 KB; CSS 12 KB; JS 3 KB; three woff2 fonts 54 KB |
| Static regression checks | `python site/check_site.py` | ok: every internal link/asset resolves; one `<h1>`, title, description, absolute canonical, JSON-LD parse on all pages; sitemap ⟷ indexable pages, `lastmod` from git; robots/404/llms.txt present; installer embeds a 40-hex pinned SHA and passes `sh -n`; the commands shown equal `facts.py`; 11 CLI subcommands named in copy exist in `modelsaar --help` |
| Browser checks | `python site/browser_checks.py --axe axe.min.js` (Playwright Chromium 1194, axe-core 4.10.3) on 9 pages × {1280 px light, 390 px dark, reduced-motion} | ok: no console errors or failed requests; no horizontal overflow at 390 px; first Tab reaches the skip link; visible 3 px focus ring on nav links; copy button announces through the live region; walkthrough tabs switch with arrow keys and keep exactly one panel open; axe serious/critical: 0 (after making scrollable code blocks/tables focusable) |
| Lighthouse (lab, mobile emulation, local server) | lighthouse 12.8.2, Chromium headless | `/`, `/get-started/`, `/how-it-works/`: performance 100, accessibility 100, best-practices 100, SEO 100; LCP 1.5–1.7 s, CLS 0, TBT 0 ms (an earlier CLS of 0.33 came from the JS mobile-nav toggle; removed — the nav now wraps without JavaScript) |
| Lighthouse (lab, desktop preset) | same | `/`: 100/100/100/100; LCP 0.4 s, CLS 0 |
| Core Web Vitals targets | — | lab LCP ≤ 2.5 s ✔, CLS ≤ 0.1 ✔, INP not measurable in lab (TBT 0 ms, max potential FID 130 ms before the nav fix, 0 after); field data at p75 will exist only after launch (CrUX needs traffic) |
| No-JavaScript | manual: scenarios are `<details>` elements with the first open; copy buttons absent; nav visible | content complete without JS |
| Installer | see `docs/live-runs/2026-10-11-installer/README.md` | Linux: pipx, uv, pip --user, repeat run, unreachable backend, occupied port; macOS arm64: uv against the GX10 — all executed; served-URL run pending domain connection |
| Preview deployment | Claude artifact (private link, page-relative build, noindex) | published for review; GitHub Pages preview/production await the owner's push (see README) |
| Not done | — | Rich Results Test on the live URL; served `install.sh` bytes from modelsaar.com; HTTPS/redirect checks on the connected domain; real-user research (this is an internal review) |

Internal review against the acceptance questions (no external users yet):
- *Can a reader unfamiliar with model infrastructure explain what ModelSaar does?* The hero plus the apps/backends/models definitions give the one-sentence version; the walkthrough shows a decision without jargon first.
- *Can they tell whether they have the prerequisites?* "Before you start" lists backend, Python/uv, platform; the installer re-checks and says what is missing.
- *Can they find and complete the first useful step?* One command on the home page and on Get started, tested on both platforms; the installer ends with the verification result and the next step.
- *Can an expert find the API contract, selection logic, limitations and evidence?* How it works §1–7, rendered `docs/routing`, benchmarks with raw records, verification report, F01–F18.
- *Does every prominent claim have support?* Every number on the site is read from `eval-live.json` at build time; support rows carry an evidence kind; status is stated on every page's footer.
- *Does every actionable control do what it says?* Copy buttons, tabs and links are exercised by `browser_checks.py`.
