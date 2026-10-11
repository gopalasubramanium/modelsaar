# Measurement plan

**Primary outcome:** a person reaches a successful first routed request and keeps using the gateway.
The website cannot observe either; the gateway sends nothing home (and will not, to measure conversion).
Everything the site can see is a *proxy*, named as such.

| event (defined before instrumenting) | meaning | source | what it is NOT |
|---|---|---|---|
| `page_view` | a request for an HTML page | host access logs (GitHub Pages: not exposed; Cloudflare Pages: Web Analytics if ever enabled) | interest, not intent |
| `install_fetch` | a GET of `/install.sh` | host logs | an installation (the script may fail or be read only) |
| `command_copy` | copy button used | **not collected** (no script phones home); would need a privacy-respecting counter — deferred until there is a reason | — |
| `source_click` | outbound click to GitHub | GitHub repository *Traffic → Referring sites* (counts modelsaar.com) | adoption |
| `issue_opened` | a GitHub issue using the integration or routing template | GitHub | satisfaction |
| `reported_first_request` | a person says the first request worked (issue, discussion, HN/Reddit comment) | manual log in `site/launch/feedback-log.md` | the only real activation signal |
| `search_impressions/clicks` | Search Console and Bing Webmaster | consoles | ranking promises |

Baselines: none exist (new site). Collect four weeks before stating any improvement; at this traffic
level prefer reading every piece of qualitative feedback over A/B tests.

Visitor controls: nothing to opt out of — no cookies, no analytics script, no forms. The privacy page
says so and will change if the measurement changes.
