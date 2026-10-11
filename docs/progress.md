# Progress and decision log

Compact state so another session can continue without repeating finished work.

## State (2026-10-11)

* Milestones A–D of the build specification are implemented; 64 tests pass (3.10 and 3.13); lint clean.
* Live checks executed on the owner's Mac against the GX10's Ollama 0.32.13 (8 models): discovery, probes,
  routing, streaming, tool calls, 3-deployment evaluation — see docs/verification-report.md. Three bugs found
  by the live run were fixed (thinking-model probe budgets, discover/doctor evidence, fingerprint vs served context).
* Repository delivered to the owner's `Model_Router/modelsaar` folder. No public repo/package/image.

## Next actions

1. Re-run `modelsaar eval --mode live --save-measurements` (all 8 deployments, detached) so measurements
   are stored under the corrected fingerprints; consider `max_tokens` ≥ 1024 for thinking models.
2. Try one real client (Open WebUI is the quickest) with `modelsaar client-config open-webui`; record a
   tool round trip in the report.
3. If live routing between two deployments works, update the README support matrix.
4. Consider the INFO items from the adversarial review (docs/research/adversarial-review-2026-10-11.md §22–28).

## Decision log

| date | decision | why |
|---|---|---|
| 2026-10-11 | Names: ModelSaar / `modelsaar` (replacing `local-model-router` / `lmr`) | owner's context.md |
| 2026-10-11 | Build small purpose-built gateway; do not extend LiteLLM / vLLM-SR / RouteLLM | ADR-001; footprint, local operation, capability-aware routing, licence boundaries |
| 2026-10-11 | Python, Starlette+uvicorn+httpx+pydantic+PyYAML only; SQLite via stdlib | five deps; direct control of streaming/disconnects; contributor accessibility |
| 2026-10-11 | Forward Ollama inference through its OpenAI-compatible layer; discover via native API | preserves Ollama's own tool semantics; native API has the truthful metadata (`/api/show` capabilities, `/api/ps`, `remote_model`) |
| 2026-10-11 | `tool_choice=required/named`, `logit_bias`, `n`, `logprobs`, remote image URLs → ineligible/rejected on Ollama path | documented Ollama limits (docs.ollama.com, 2026-10-11); never silently altered |
| 2026-10-11 | Unknown capability or unknown context length ⇒ not eligible | spec: treat unknown conservatively; review finding 1 |
| 2026-10-11 | Served Ollama context assumed 4096 unless Modelfile/ps/override | Ollama exposes no served value for unloaded models; doctor warns |
| 2026-10-11 | Response `model` field = requested alias by default; deployment in `X-ModelSaar-Deployment` | clients that validate ids; diagnostics stay out of content |
| 2026-10-11 | Failover only pre-commit, max 1 attempt, same candidate list; stream truncation without finish_reason reported as error | spec §10; review finding 4 |
| 2026-10-11 | Session affinity pinned after successful dispatch; tool round trips keyed by the last assistant turn's ids only | review findings 3 and 21 |
| 2026-10-11 | Uncalibrated prior = 0.5 + 0.05·log10(1+params_B), capped 0.75, labelled; ties (±0.03 priors / ±unc/2 measured) resolve to lower overhead | spec: prefer lower overhead when effectively tied; size is a labelled hypothesis only |
| 2026-10-11 | Catalogue supplies priors/tags/roles/notes only; never served context or verified capabilities | separate claims from probes and measurements |
| 2026-10-11 | Decision models (clef, nimble, tev1, laya), guardian, OCR → roles that never receive chat | spec §11 |
| 2026-10-11 | Mistral Large 4 = announced weights; tev1 licence unresolved → disabled in catalogue | primary sources 2026-10-11 |
| 2026-10-11 | Exact tokenization only for borderline cases on runtimes with `/tokenize` | bounded overhead; review finding 11 |
| 2026-10-11 | No hot config reload in 0.1 (restart) | simplicity; docs corrected |
| 2026-10-11 | Evaluation: no LLM judge; executable/exact scoring; rules baseline is given the gold label (disclosed) | spec §14 |

## Research artefacts

docs/research/: foundations (build-vs-adapt), clients (four client configs), catalogue parts 1–2,
adversarial review — all dated 2026-10-11 with URLs.
