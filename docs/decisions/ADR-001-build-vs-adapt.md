# ADR-001: Build a small purpose-built gateway; compose, do not extend

Status: accepted (2026-10-11). Evidence: [research/foundations-2026-10-11.md](../research/foundations-2026-10-11.md)
(every claim there is tagged verified-from-primary-source with URL and date, or unverified).

## Context

ModelSaar must: run local-first with no paid API, cloud classifier, GPU library or mandatory
downloaded model; discover deployments from user-managed runtimes (Ollama first); route by
*verified* capabilities, context fit, hardware/residency and measured performance; preserve client
semantics (tools, media, schemas, streaming); explain decisions; install with one command.

## Options examined (current released versions, checked 2026-10-11)

| option | what it actually does | why it does not fit as the base |
|---|---|---|
| **vLLM Semantic Router** v0.4 (Apache-2.0; Go + Rust + Python) | Real intent/capability-aware selection; Chat Completions + Responses + Anthropic Messages with fail-closed translation; replay/explainability | `vllm-sr serve` requires Docker/Podman and starts **Envoy**; backends are static YAML (no Ollama discovery); downloads many ~1.2 GB ONNX encoder models (intent, PII, jailbreak, …) plus a 0.6B embedder; optional Milvus/Redis; no embeddings endpoint; pre-1.0 and fast-changing. |
| **LiteLLM** 1.104 (MIT core + proprietary `enterprise/`) | Mature multi-provider proxy; ordinary Router = load balance/fallback/cooldown (capability-aware only for context window + region); Auto Routing is **beta** with heuristic/LLM/embedding classifiers whose examples lean on hosted services; Adaptive Router is beta and needs Postgres | No tools/vision/schema filtering; no Ollama discovery; `proxy` extra pulls 31 packages including `litellm-enterprise` and cloud SDKs; routing core would be fought rather than reused. Plausible *optional downstream* for cloud providers later. |
| **RouteLLM** 0.2.0 (Apache-2.0) | Strong/weak two-model routing with trained routers | Effectively unmaintained (last release 2024-07); strictly two models; `mf`/`sw_ranking` call OpenAI embeddings per request; torch/transformers dependency. Useful only as an idea (calibrate on a local benchmark). |
| llama-swap, Portkey, Bifrost, LocalAI, aurelio semantic-router, Not Diamond | Lifecycle/VRAM swapping (llama-swap), load balancing, infra routing, intent matching | None selects by verified capability + context + residency; llama-swap is a good *complement* for process lifecycle (a later, opt-in milestone). |

## Decision

Implement ModelSaar as one Python process (Starlette + uvicorn + httpx + pydantic + PyYAML; five
runtime dependencies) with:

* adapters for Ollama (native metadata + OpenAI-compatible forwarding) and generic OpenAI-compatible
  servers, registered through a plugin table so new runtimes do not touch the router;
* a deployment registry with three-state capabilities and provenance, fingerprints that invalidate
  probe evidence, and SQLite persistence (stdlib);
* an explicit pipeline: requirements → hard filters → cheap classification (optional local
  classifier) → transparent ranking → decision record;
* admission control, affinity, pre-commit-only failover, and privacy defaults as product behaviour;
* an executable evaluation harness with fixed/rules/random/oracle baselines.

Borrowed ideas (no code): vLLM Semantic Router's signals→decision and replay design and fail-closed
field translation; RouteLLM's calibrate-then-evaluate discipline; llama-swap's single-process
simplicity.

Rejected: Go instead of Python (Python keeps the barrier to contribution low for the target users and
the dependency count is already minimal); FastAPI (Starlette alone gives direct control over
streaming and disconnects with fewer layers).

## Consequences

* Source install works immediately; no published package or image is claimed.
* Responses API and Anthropic Messages are explicit 501s until implemented as separate work.
* Model lifecycle (load/unload) stays with the user's runtime; a later milestone may compose with
  llama-swap or Ollama's keep-alive controls under leases.
