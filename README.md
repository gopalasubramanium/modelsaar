# ModelSaar

[![ci](https://github.com/gopalasubramanium/modelsaar/actions/workflows/ci.yml/badge.svg)](https://github.com/gopalasubramanium/modelsaar/actions/workflows/ci.yml)

**Intelligent routing for local AI models.** One endpoint. Intelligent model selection.

ModelSaar is a small, local-first, OpenAI-compatible gateway. Your applications (Open WebUI,
OpenClaw, OpenCode, Hermes Agent, anything that speaks Chat Completions) connect once and ask for a
virtual model such as `auto`. ModelSaar inspects each request, keeps only the deployments that can
*actually* satisfy it (tools, images, strict JSON schemas, context size, locality, health, capacity),
ranks the rest on evidence, forwards the request unchanged, and records a decision you can inspect.

```
client ──/v1/chat/completions (model: auto)──▶ ModelSaar ──▶ ollama/qwen3.8:27b
                                                  │            ollama/gemma4:e4b
                                                  │            vllm/...
                                                  └─ X-ModelSaar-Deployment, /admin/explain
```

Status: **0.1.0 — first release candidate.** Core routing, streaming, embeddings, probes, CLI,
client config generation, evaluation harness and a fault-injection test suite are implemented and
tested against controlled backends, and exercised live against a real Ollama server with eight models
(discovery, probes, routing, streaming, tool calls, evaluation). Read the
[verification report](docs/verification-report.md) before relying on any specific compatibility.

## Why

* **Connect once.** Clients keep their own agent loops, tools, memory and UI; ModelSaar only selects
  and forwards inference requests.
* **Never silently degrade.** No truncated history, dropped images, weakened schemas, stripped
  tools, or hidden cloud fallback. If nothing qualifies you get a structured error with blockers and
  remedies.
* **Evidence over marketing.** Capabilities are three-state (`supported | unsupported | unknown`)
  with provenance (runtime metadata, probe, operator). Quality estimates are labelled *measured*,
  *prior* or *uncalibrated*. Unknown required capabilities never qualify.
* **Local and private by default.** Loopback bind, generated keys, no prompt logging, cloud-forwarded
  models excluded unless you opt in, backends only reachable at their configured hosts.
* **Small.** Five runtime dependencies (Starlette, uvicorn, httpx, pydantic, PyYAML). No Docker,
  Envoy, Redis, Postgres, GPU toolkit or mandatory classifier model.

## Quickest working setup

Prerequisites: Python 3.10+, and a running local inference server with at least one model
(Ollama is the first-class path; any OpenAI-compatible server works with declared models).

```bash
# 1. install from source (no PyPI package is published yet)
git clone https://github.com/gopalasubramanium/modelsaar.git && cd modelsaar
python3 -m venv .venv && . .venv/bin/activate      # or: uv venv && . .venv/bin/activate
pip install -e .                                   # or: uv pip install -e .

# 2. initialise: finds Ollama on 127.0.0.1:11434 (or pass --endpoint), writes config + keys, discovers models
modelsaar init

# 3. check and verify
modelsaar doctor            # reachability, context assumptions, unknown capabilities, cloud aliases
modelsaar probe --all       # live checks: streaming, tools, JSON schema, vision, latency (uses local compute)

# 4. run
modelsaar serve             # http://127.0.0.1:8484/v1 ; keys in ~/.modelsaar/keys/

# 5. first request (in another shell)
modelsaar test              # identifies the gateway (GET /healthz), GET /v1/models, one routed completion through `auto`
```

Example request:

```bash
curl -s http://127.0.0.1:8484/v1/chat/completions \
  -H "Authorization: Bearer $(head -1 ~/.modelsaar/keys/api_keys)" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Write a Python function that parses ISO dates"}]}' \
  -D - | grep -i x-modelsaar      # X-ModelSaar-Deployment tells you what was selected
```

Then connect a client. One command per client (pick yours; these are separate commands, not a
pipeline): `modelsaar client-config open-webui`, `modelsaar client-config openclaw`,
`modelsaar client-config opencode` (or `opencode-v2`), `modelsaar client-config hermes`. Each prints
verified configuration; `--apply` merges file-based configs with a backup. For a GUI field that asks
for an API key, print the key in a terminal with `head -1 ~/.modelsaar/keys/api_keys` and paste the
value it prints (a line starting with `msk_`) — the `$(...)` form above is shell syntax, not a key. See
[docs/clients/](docs/clients/).

No models yet? `modelsaar demo` starts a clearly labelled **simulated** backend so you can try the
CLI, the status page and route explanations without downloading anything.

## Virtual models (aliases)

| alias | profile | notes |
|---|---|---|
| `auto` | quality | default: best expected quality within limits; effectively tied candidates resolve to the lower-overhead one |
| `auto-quality` | quality | same as `auto` |
| `auto-balanced` | balanced | more weight on latency and residency |
| `auto-fast` | fast | prefer resident, low-latency deployments |
| `auto-code` | quality | only deployments tagged `code` |
| `auto-vision` | quality | only deployments with verified image input |

Aliases are advertised in `GET /v1/models` **only** when at least one usable deployment backs them,
with a truthful contract (`context_length_min`, tools/vision/json_schema = supported/partial/unsupported).
Any concrete deployment id (e.g. `ollama/qwen3.8:27b`) can be requested directly; it still passes
the same hard checks.

## How a route is chosen

1. **Requirements** – structural analysis of the whole request: roles, images/audio, tools and
   `tool_choice`, `response_format`, outstanding tool-call ids, `reasoning_content`, conservative
   token accounting (input + output allowance + reasoning budget for thinking models).
2. **Hard filters** – role, health, locality policy, capability tri-state, effective context,
   backend field support, admission feasibility. A score can never override a failed filter.
3. **Classification** – deterministic multi-label task signals; an *optional* local classifier is
   consulted only for ambiguous cases, under a strict JSON contract with timeout and fallback.
4. **Ranking** – transparent score per profile: evidence-based quality (measured > prior >
   uncalibrated, with uncertainty) minus latency, residency/load and overhead costs, plus a
   switching penalty for session affinity.
5. **Decision record** – request id, config hash, inferred task, requirements, exclusions with
   reasons, candidate breakdown, chosen deployment, evidence level, overhead. No prompt content.

Inspect: `modelsaar explain -m "..." [--tools --image --json-schema]`, `modelsaar decisions`,
`GET /admin/decisions/<id>`, or the status page at `/admin/ui`. Details: [docs/routing.md](docs/routing.md).

## Tested support matrix

Legend: **F** fixture-tested over real HTTP with a controlled fake backend (CI); **L** executed live
against real models (owner's GX10 via Tailscale, 2026-10-11); **D** documented from primary sources
(config keys verified 2026-10-11); **NOT RUN** needs your hardware/client.

| area | status |
|---|---|
| `GET /v1/models`, `POST /v1/chat/completions` (non-stream + SSE), `POST /v1/embeddings`, `/healthz`, `/readyz` | F |
| Ollama adapter: `/api/tags`, `/api/show`, `/api/ps`, `/api/version`, OpenAI-compat forwarding, cloud-alias detection | F + **L** (Ollama 0.32.13 on an ASUS GX10, 8 models, 2026-10-11) |
| Generic OpenAI-compatible adapter (`/models`, `/chat/completions`, `/embeddings`, vLLM `/tokenize`) | F (fixture), **NOT RUN** against vLLM/llama.cpp |
| Tool round trips, streaming tool deltas, strict schema routing, image routing | F |
| Failover before commitment / termination after commitment | F |
| Admission limits, queue rejection, uncertain occupancy on disconnect | F |
| Probes, fingerprint invalidation (endpoint + identity), embedding contracts (verified identity, output validation), local-only policy | F |
| Privacy before payload operations (no `/tokenize`/classifier traffic to policy-excluded deployments), continuity (no failover inside tool round trips / pinned sessions), timeout holds, pool memory budgets, probes under gateway admission | F (`tests/test_hardening_2026_10_11.py`) |
| Open WebUI / OpenClaw / OpenCode V1+V2 / Hermes configuration | D; live tool round trip **NOT RUN** |
| Several real deployments routed by `auto` (chat → qwen3.6, code/tools → qwen3-coder, vision → qwen3.6, agent → gemma4) | **L** — see [docs/verification-report.md](docs/verification-report.md) |
| Live evaluation vs fixed/rules/random/oracle baselines (3-deployment subset) | **L** (2026-10-11, pre-hardening evaluator: auto 0.875 vs fixed-strong 0.906, overlapping CIs, 0 capability violations — historical; a rerun with the repaired evaluator is recorded in docs/verification-report.md when complete) |
| Responses API, Anthropic Messages | not implemented (explicit 501) |

## Limitations (0.1)

* Served context length for Ollama models is **assumed 4096** unless the Modelfile sets `num_ctx`,
  the model is currently loaded (`/api/ps`), or you add an override; `doctor` warns about it.
* Token counts are conservative estimates (chars/3 for Latin text, one token per CJK/other wide character, plus overheads); when a backend exposes `/tokenize` (vLLM) the gateway asks it for text counts only in borderline cases (estimate within ±50 % of a deployment's context), only for deployments that already passed every policy filter, and still adds estimated template/image overhead.
* Pool `memory_gb` budgets use weights-only estimates plus a margin; they prevent clearly oversized dispatches, not every OOM.
* Ollama's OpenAI layer does not support `tool_choice=required/named`, remote image URLs,
  `logit_bias`, `n`, `logprobs`; such requests are rejected with blockers rather than altered.
* Audio/video inputs, multimodal embeddings, OCR and decision-model pipelines, Responses API,
  Anthropic Messages, managed model loading/unloading, cascades and learned policies are out of
  scope for 0.1 (see [docs/roadmap.md](docs/roadmap.md)).
* The evaluation harness executes model-written code only under bubblewrap / `sandbox-exec` / Docker; without one of those, code tasks are skipped (reported), never run on the host.
* Quality priors from the catalogue are hypotheses; run `modelsaar eval --mode live --save-measurements`
  to replace them with measurements on your hardware.

## Documentation

* [Installation](docs/installation.md) · [Troubleshooting](docs/troubleshooting.md) · [Privacy & security](docs/privacy.md)
* [Architecture](docs/architecture.md) · [Routing](docs/routing.md) · [ADR-001 build vs adapt](docs/decisions/ADR-001-build-vs-adapt.md)
* [Model catalogue evidence](docs/catalogue.md) · [Adding a deployment or adapter](docs/extending.md)
* Client guides: [Open WebUI](docs/clients/open-webui.md) · [OpenClaw](docs/clients/openclaw.md) · [OpenCode](docs/clients/opencode.md) · [Hermes Agent](docs/clients/hermes.md)
* [Evaluation](docs/evaluation.md) · [Verification report](docs/verification-report.md) · [Release process](docs/release.md) · [Roadmap](docs/roadmap.md)
* [Progress & decision log](docs/progress.md)

## Licence

Apache-2.0 for the gateway code (see `LICENSE`, `NOTICE`). Model weights are licensed by their
publishers; ModelSaar neither bundles weights nor accepts any model terms on your behalf.
