# Search-intent map and technical SEO status

Each substantive page answers one real question. Keyword-volume and CPC data: **unknown** (no planner
access); themes are taken from how people phrase the problem in community threads, not from measured
volume.

| question people ask | page | answer-first passage (first paragraph) |
|---|---|---|
| "How do I use several local models from one app without switching?" / "local LLM router" | `/` | hero + "Several good models, one app at a time" |
| "Ollama model router" / "one endpoint for Ollama for all my apps" | `/get-started/`, `/integrations/` | prerequisites, `modelsaar init` finds Ollama; backends section |
| "connect Open WebUI / OpenCode to local models through a gateway" | `/docs/clients/*` | per-client connection settings, Docker addresses |
| "route by capability: tools, vision, JSON schema" / "LLM gateway capability aware" | `/how-it-works/` | hard filters section, three-state capabilities |
| "local inference privacy gateway, no cloud, no telemetry" | `/privacy/` | gateway section |
| "explain why a model was selected" / "LLM routing decision log" | `/how-it-works/#rec-title`, `/docs/routing/` | decision record section |
| "does LLM routing actually help / benchmark" | `/benchmarks/` | method + recorded run + what it does not show |
| "ModelSaar vs LiteLLM / vLLM semantic router / RouteLLM" | not a page (would be thin and promotional); the dated comparison lives in `docs/research/foundations-2026-10-11.md` and ADR-001, linked from the roadmap | — |

Implemented in code (`site/build.py`): titles, descriptions, one H1 per page, canonical `https://modelsaar.com`
(www redirects at the host), trailing-slash directory URLs, semantic HTML, descriptive internal links,
`sitemap.xml` with git-derived `lastmod`, `robots.txt` (preview builds: `Disallow: /` + `noindex`),
`404.html`, Open Graph + Twitter card with an absolute 1200×630 image, JSON-LD `WebSite`,
`SoftwareSourceCode` (home) and `WebPage` + `BreadcrumbList` (inner pages). No `SoftwareApplication`
markup: Google's software-app rich result requires an aggregate rating or offer, which we will not invent;
no FAQ rich-result expectation (FAQPage rich results are limited to government/health sites per Google's
2023 change). `llms.txt` is served as a convenience index, not a ranking mechanism. Structured data
validity was checked by parsing (JSON) in `site/check_site.py`; rich-result eligibility is a separate,
unclaimed matter — run Google's Rich Results Test after deployment.

Verification and submission: Search Console and Bing Webmaster need the owner's account.
Prepared: add the HTML-tag verification `<meta name="google-site-verification" …>` /
`<meta name="msvalidate.01" …>` to `site/build.py` (`layout()` head) once the owner creates the
properties, rebuild, deploy, then submit `https://modelsaar.com/sitemap.xml` in both consoles. DNS-TXT
verification at Cloudflare is the alternative that needs no rebuild.
