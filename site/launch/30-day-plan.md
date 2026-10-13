# 30-day launch plan (starts when the hardening PR is public and modelsaar.com resolves)

Goal for the month: a handful of real people reach a first routed request and report back; one
real-client workflow recorded end to end; one external backend (vLLM or llama.cpp) verified. Reach is an
aspiration to test, not a deliverable. Zero paid spend unless separately authorised.

| week | do | measure |
|---|---|---|
| 1 | Make the hardening PR reviewable (CI green, F01–F18 table). Publish the site. Submit sitemap to Search Console and Bing. Record the walkthrough video from the script (or keep the storyboard labelled "not recorded"). Open issue templates. | Search Console coverage report; GitHub repository Traffic (visitors, clones, referring sites) — page views and installer fetches are not observable on GitHub Pages. |
| 2 | Show HN (one post, owner answers all day). Same day: the launch article on the site. No other channel that day. Triage every issue within 24 h; fix docs the same day. | HN thread questions → FAQ items; GitHub issues opened; first "decision record that surprised me" report. |
| 3 | r/LocalLLaMA post in the owner's own words (rule: not LLM-generated), one Ollama community post, one Open WebUI discussion asking for a tester. Record the first real-client workflow (Open WebUI) and add it to the verification report. | Integration feedback issues; one recorded client workflow. |
| 4 | Write up what changed because of feedback (changelog + short post). Run the evaluation with a reasoning-matched budget and all eight models; publish honestly whatever it shows. Decide on the 0.1.x release with the PR reviewer. | Number of distinct reporters (issues, discussions, `feedback-log.md`); GitHub Traffic trend; release decision. Repeat visitors are not observable without analytics and are not measured. |

Rules throughout: disclose affiliation; one post per community; no reposting within a week; no claims
beyond `docs/verification-report.md`; respond to criticism with evidence or a fix, not a defence.
