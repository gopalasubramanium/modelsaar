# Show HN draft

Rules checked 2026-10-11 (https://news.ycombinator.com/showhn.html): something people can try; no sign-up; the author answers questions in the thread; title starts with "Show HN:". Do not ask anyone to upvote.

**Title (≤80 chars):**
Show HN: ModelSaar – one OpenAI-compatible address that routes to your local models

**Post text:**

I run several local models (Ollama on a small box) and got tired of re-selecting the right one in every app. ModelSaar is a small Apache-2.0 Python gateway: apps connect once and ask for `auto`; per request it keeps only the deployments that can actually do the job (tools, images, strict JSON, context size, local-only policy, health, capacity) on verified capability evidence, ranks the rest on measured task success or labelled priors, forwards the request unchanged, pins tool round trips and sessions to the same model, and writes a decision record you can inspect — without the prompt.

What it is not: it doesn't ship models, replace Ollama/vLLM, or add an LLM judge. Unknown capabilities never qualify a model; if nothing qualifies you get a 422 with blockers and remedies, never a silently degraded answer.

Honest numbers: on one recorded run (3 models, 32 held-out tasks) `auto` and the best single model each scored 30/32; `auto` completed 32 vs 31 requests (the image task the fixed model can't take), recorded 0 vs 1 capability violations, and had a p95 end-to-end latency of 7.96 s vs 4.76 s because two requests went to a slow thinking model (routing overhead itself: 0.98 ms p95). n=32, CIs overlap — it shows where routing helps (coverage, transparency), not that it's better in general. Raw per-request records and a script that regenerates every number are in the repo.

An independent review found 18 real defects in the first public revision (privacy of tokenizer calls, failover inside tool round trips, memory budgets, embedding identity, evaluator scoring, file permissions…); the fixes and regression tests are in a draft PR you can read.

Status: development preview, no release yet. Needs Python 3.10+ and a backend with a model. `curl -fsSL https://modelsaar.com/install.sh | sh` (pins a reviewed commit; read it first at https://modelsaar.com/get-started/).

Site: https://modelsaar.com · Source: https://github.com/gopalasubramanium/modelsaar

I'd especially like to hear from people running vLLM/llama.cpp (only Ollama is verified live) and from Open WebUI/OpenCode users (configs are generated from the docs, not yet recorded end to end).
