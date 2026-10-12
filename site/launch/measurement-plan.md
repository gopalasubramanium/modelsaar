# Measurement plan

**Primary outcome:** a person reaches a successful first routed request and keeps using the gateway.
The website cannot observe either; the gateway sends nothing home (and will not, to measure conversion).
Everything the site can see is a *proxy*, named as such.

| event (defined before instrumenting) | meaning | source | what it is NOT |
|---|---|---|---|
| `page_view` | a request for an HTML page | **unavailable** on the chosen hosting (GitHub Pages exposes no access logs; no analytics script is loaded) | interest, not intent |
| `install_fetch` | a GET of `/install.sh` | **unavailable** (same reason); the only observable proxy is GitHub *Traffic → Clones/Visitors* for the repository the installer fetches from | an installation (the script may fail or be read only) |
| `command_copy` | copy button used | **not collected** (no script phones home); would need a privacy-respecting counter — deferred until there is a reason | — |
| `source_click` | outbound click to GitHub | GitHub repository *Traffic → Referring sites* (counts modelsaar.com) | adoption |
| `issue_opened` | a GitHub issue using the integration or routing template | GitHub | satisfaction |
| `reported_first_request` | a person says the first request worked (issue, discussion, HN/Reddit comment) | manual log in `site/launch/feedback-log.md` | the only real activation signal |
| `search_impressions/clicks` | Search Console and Bing Webmaster | consoles | ranking promises |

Observable today, in order of usefulness: `reported_first_request` (qualitative, manual), `issue_opened`, GitHub repository Traffic (visitors, clones, referring sites), Search Console/Bing once verified. Page views and installer fetches are *not* observable on GitHub Pages and no plan should quote them.

Baselines: none exist (new site). Collect four weeks before stating any improvement; at this traffic
level prefer reading every piece of qualitative feedback over A/B tests.

Visitor controls: nothing to opt out of — no cookies, no analytics script, no forms. The privacy page
says so and will change if the measurement changes.
