# Community posts — drafts and rules (checked 2026-10-11)

These are *drafts for the owner to rewrite in their own words*. Several communities prohibit posts that are
primarily LLM-generated; the owner should post as themselves, disclose affiliation, answer questions, and
not cross-post the same text everywhere. Post nothing until the hardening PR is public and the site is live.

## r/LocalLLaMA
Rules (wiki index, fetched 2026-10-11): search before posting; content must relate to local AI; low-effort
and **posts that are completely or primarily LLM-generated are removed**; self-promotion ≤ 10 % of your
activity and affiliation disclosed; 5 subreddit karma needed to post. Flair: *Resources* or *Other*.
Angle that fits the community: the capability-evidence model (tri-state capabilities with provenance,
probes), the honest benchmark, and the privacy findings. Lead with a decision record screenshot and the
numbers, not with the install line.

Owner's own-words outline: what you run (GX10, Ollama, 8 models), the annoyance that started it, what the
gateway checks before routing, the one-run result and its limits, what you want feedback on (vLLM users,
thinking-model budgets, Open WebUI session headers).

## r/selfhosted
Same disclosure norms; the self-hosted angle: one key, loopback by default, no telemetry, runs beside Open
WebUI, Docker Compose with keys bootstrapped on first start. Link the privacy page.

## Ollama community (GitHub Discussions / Discord "projects" channel)
Angle: uses Ollama's native API for truthful metadata (/api/show capabilities, /api/ps residency,
remote_model detection) and forwards through its OpenAI layer so tool semantics are untouched; documents
the served-context assumption and how `doctor` flags it. Ask for feedback on the assumed-4096 behaviour.

## Open WebUI discussions
Angle: the connection snippet (`/v1` URL, auto-listed models), `X-OpenWebUI-Chat-Id` for session
pinning, `TASK_MODEL_EXTERNAL=auto-fast`. Be explicit that the client workflow is documented, not yet
recorded end to end, and ask for a tester.

## Lobsters (if the owner has an account)
Tag `ai`, `release` is not appropriate (no release). Lobsters discourages self-promotion without
participation; post only if already active there.

## What not to do
No DMs, no "found this cool tool" posts, no re-posting the same text within a week, no claims beyond the
verification report, no star-count or adoption claims (there are none).
