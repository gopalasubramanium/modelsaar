# Measured Routing Quality — Stage A manifest (GX10 baseline, 2026-10-14)

Inventory, identity, capability and low-cost characterisation of the GX10 environment before Stage B.
Read / measure / record / plan only: no routing, classifier, model, Ollama, configuration or service
change was made; the GX10's production `modelsaar.service` was not touched. Machine-readable
companions: `environment.json`, `deployments.json`, `capabilities.json`, `smoke-metrics.json`; raw
command outputs under `raw/` (keys, prompts and licence/modelfile text excluded; the Mac user path is
written as `~`).

## A. Execution baseline

| item | value | evidence |
|---|---|---|
| Date/time, zone | 2026-10-14 16:37–16:49 IST (UTC+05:30) | `raw/…` headers; `10-collect.txt` |
| Repository `main` | `f18b2f195478d9a6591e7c637c321a46d9420e7e` | `git ls-remote` |
| Gateway package on the GX10 | `cf56cdd3416d8c853b64111b9b40211e5b126031` — **owner-reported** (2026-10-14 upgrade summary); not re-verified: port 8484 unreachable from the Mac on `100.83.54.124` and `192.168.0.12` (connection refused) | `10-collect.txt` |
| Gateway package used for Stage A measurements | the same revision `cf56cdd…` (`modelsaar 0.1.0`), installed on the Mac by the public installer on 2026-10-13 and run as a Mac-local gateway (loopback, port 50824, `max_concurrent 1`) with a separate Stage A home | `environment.json` |
| GX10 service state / effective endpoint | owner-reported active at `http://192.168.0.12:8484/v1`; **NOT OBSERVED** in Stage A | — |
| Ollama | **0.40.3** at `http://100.83.54.124:11434` (Tailscale) — the 2026-10-11 run used 0.32.13 | `raw/ollama-version.json` |
| OS / kernel / arch, hardware identity, unified memory, storage, GPU visibility | **NOT EXPOSED** over the Ollama API (no shell path to the GX10 in this session); `/api/ps` reports `size_vram == size` for every loaded model (fully resident as Ollama sees it); two models (up to 55 GB + 18 GB) were resident at once during the run | `raw/ollama-ps-*.json` |
| Ollama model inventory | 8 models (`raw/ollama-tags.json`); same names as the 2026-10-11 list — re-discovered live | |
| ModelSaar deployment inventory | 8 generative deployments, all healthy, locality `local` (operator-declared backend locality via `init`) | `raw/discover.json` |
| Config hash (Stage A home) | `c58ce04fa1ed9902` (doctor); GX10 config hash **NOT READABLE** | `raw/doctor.json` |
| Routing defaults (cf56cdd) | profile `quality` (quality 1.0 / latency 0.15 / residency 0.1 / overhead 0.05), switching penalty 0.08, uncalibrated prior 0.5, pre-commit failover 1 attempt | `environment.json` |
| Classifier | **disabled** (default; `enabled: false`, timeout 2.0 s, `only_when_ambiguous: true`, local only); GX10 value UNKNOWN (not readable; default is disabled and no enabling was reported) | `environment.json` |
| Residency before measurements | `/api/ps` empty at 16:37 | `raw/ollama-ps-before.json` |

## B. Model identity (`deployments.json`)

All eight identities are **verified**: ModelSaar uses the Ollama digest as identity (`identity_source:
ollama digest`) and folds digest, template hash, quantization and runtime version into the fingerprint.

| deployment | digest | params · quant · weights | arch | trained ctx (model_info) | Modelfile `num_ctx` | ModelSaar ctx at discovery | Ollama served ctx (`/api/ps`) | ModelSaar tags | fingerprint |
|---|---|---|---|---|---|---|---|---|---|
| muse-glimmer:latest | `de878ce33ad8` | 27.9B · Q4_K_M · 18.2 GB | muse-glimmer | 131072 | — | 4096 (assumed) | NOT OBSERVED | general, agent, vision | 31f1aafa7391ca95 |
| qwen3.6:latest | `096fdbd02fe6` | 35.5B · Q4_K_M · 22.6 GB | qwen35moe | 262144 | — | 4096 (assumed) | NOT OBSERVED | general, reasoning, code, vision | 7495ed65fbf1dbd5 |
| gemma4:31b | `6316f0629137` | 31.3B · Q4_K_M · 19.9 GB | gemma4 | 262144 | — | 4096 (assumed) | NOT OBSERVED | — | c2a3b30b88068a13 |
| qwen3.8:latest | `aaee06c39dcf` | 27.3B · Q4_K_M · 17.7 GB | qwen35 (dense) | 262144 | — | 4096 (assumed) | **131072** | general, reasoning, code, vision | 06621e3e0e6844f0 |
| qwen3-coder-next:latest | `ca06e9e4087c` | 79.7B · Q4_K_M · 51.7 GB | qwen3next | 262144 | — | 4096 (assumed) | NOT OBSERVED | — | 3403278e77d95723 |
| qwen3-coder:latest | `06c1097efce0` | 30.5B · Q4_K_M · 18.6 GB | qwen3moe | 262144 | — | 4096 (assumed) | NOT OBSERVED | code, agent | 4eacb9bbc87cccbf |
| qwen3.6-accurate:latest | `6561b007fb01` | 36.0B · Q4_K_M · 23.9 GB | qwen35moe | 262144 | 131072 | 131072 (Modelfile) | NOT OBSERVED | — | e972c9b803aecfc4 |
| qwen3.6-fast:latest | `b6f8526faefe` | 36.0B · Q4_K_M · 23.9 GB | qwen35moe | 262144 | 65536 | 65536 (Modelfile) | 65536 | — | 9274883c38d48361 |

Families/architectures come from Ollama's `details`/`model_info`, not from names. External reference
data about these families was not consulted and is not part of the identity record.

## C. Capability verification (`capabilities.json`; `modelsaar probe --all --timeout 180`, 382 s, through the local gateway's admission, one deployment at a time)

| deployment | Ollama declares | streaming | tools | parallel tools | json_object | json_schema | vision | probe ttft / warm p50 (ms) |
|---|---|---|---|---|---|---|---|---|
| muse-glimmer:latest | completion, vision, tools, thinking | supported | supported | supported | supported | supported | **unsupported** (image accepted; colour not identified) | 7345 / 6921 |
| qwen3.6:latest | completion, vision, tools, thinking | supported | supported | supported | supported | supported | supported | 7154 / 1251 |
| gemma4:31b | completion, vision, tools, thinking | supported | supported | supported | supported | supported | supported | 15120 / 4530 |
| qwen3.8:latest | completion, vision, tools, thinking | supported | supported | supported | supported | supported | supported | 7694 / 1054 |
| qwen3-coder-next:latest | completion, tools | supported | supported | supported | supported | supported | unsupported (declared; not probed) | 12876 / 140 |
| qwen3-coder:latest | completion, tools | supported | supported | supported | supported | supported | unsupported (declared; not probed) | 6776 / 101 |
| qwen3.6-accurate:latest | completion, vision, tools, thinking | supported | supported | supported | supported | supported | supported | 8155 / 1607 |
| qwen3.6-fast:latest | completion, vision, tools, thinking | supported | **unsupported** (no `tool_calls` for an explicit tool request) | NOT RUN (tools unsupported) | supported | supported | supported | 7635 / 1561 |

No probe timed out, errored or was deferred (`uncertain: false`, `skipped: []` for all eight). Before
probing, `json_schema` was `unknown` and `parallel_tools` `unknown` on every deployment; `tools`/`vision`/
`thinking` were source claims. Not probed by the contract: `continuation`, `tool_choice_required`
(adapter says unsupported), `audio_in`, `thinking`. Probe request ids are not exposed by the probe
report; the 40 smoke requests have request ids in `smoke-metrics.json` / `raw/decisions.txt`.

## D. Context baseline

- Theoretical/declared (model card via `model_info.*.context_length`): 262144 for the Qwen and Gemma
  models, 131072 for muse-glimmer.
- Ollama served context: only observable while loaded (`/api/ps.context_length`): **131072 for
  qwen3.8** (no Modelfile `num_ctx`, so this is Ollama 0.40.3's effective default on the GX10) and
  65536 for qwen3.6-fast (its Modelfile). Other models: NOT OBSERVED (not resident when read).
- ModelSaar at discovery: Modelfile `num_ctx` where present (qwen3.6-accurate 131072, qwen3.6-fast
  65536), otherwise the **assumed** 4096 until the model is seen loaded (documented limitation).
- Uncertain: the six deployments without Modelfile `num_ctx` — their routing context is 4096 until a
  `/api/ps` observation; Stage B's `--probe` step loads each subset model and resolves this per run.

## E. Low-cost smoke characterisation (`smoke-metrics.json`; 40 requests; latencies include the Mac→GX10 Tailscale path)

| deployment | state before first request | first request total (ttft) ms | warm chat total (ttft) ms | est. cold load ms | throughput prompt | json_object | tool call | resident after (size_vram) |
|---|---|---|---|---|---|---|---|---|
| muse-glimmer:latest | not resident | 13665 (13590) | 7092 (7009) | ~6600 | `length`, 0 content chars | `length` (128 tok, no answer) | tool_calls `get_weather` | yes (17.6 GB) |
| qwen3.6:latest | not resident | 8953 (8950) | 1304 (1301) | ~7600 | `length`, 0 | `length` (128 tok) | none (`length`) | yes (22.9 GB) |
| gemma4:31b | not resident | 12743 (12639) | 4633 (4540) | ~8100 | `length`, 0 | `stop` (105 tok) | tool_calls `get_weather` | yes (22.6 GB) |
| qwen3.8:latest | resident (from probes) | 1016 (899) | 1001 (899) | — | `length`, 155 chars · 29 chunks/s | `stop` (44 tok) | tool_calls `get_weather` | yes (18.5 GB) |
| qwen3-coder-next:latest | not resident | 12982 (12952) | 142 (122) | ~12800 | `stop`, 170 chars · 41 chunks/s | `stop` (17 tok) | tool_calls `get_weather` | yes (55.4 GB) |
| qwen3-coder:latest | not resident | 6722 (6718) | 113 (93) | ~6600 | `stop`, 170 chars · 60 chunks/s | `stop` (17 tok) | tool_calls `get_weather` | yes (32.1 GB) |
| qwen3.6-accurate:latest | not resident | 9112 (9091) | 1589 (1566) | ~7500 | `length`, 0 | `length` (128 tok) | none (`length`) | yes (26.2 GB) |
| qwen3.6-fast:latest | not resident | 8852 (8829) | 1623 (1609) | ~7200 | `length`, 0 | `length` (128 tok) | skipped (tools unsupported per probe) | yes (24.6 GB) |

Readings: TTFT counts the first **content** delta (reasoning deltas excluded), so for thinking models
TTFT ≈ total on short answers; "throughput" is content chunks/s, not tokens/s; `size_vram` after the run
exceeds the weights size where a large served context's KV cache was allocated (qwen3-coder 32.1 GB vs
18.6 GB weights; qwen3-coder-next 55.4 GB vs 51.7 GB). Every model stayed resident after its requests
(Ollama keep-alive; two models resident at once). The thinking models spent the 128/200-token smoke
budgets on reasoning and returned no content on the JSON/counting prompts — recorded as the
reasoning-budget hazard in `evaluation-contract.md`; no quality conclusion is drawn.

## J. Classifier status (unchanged)

Disabled on the Stage A home (default); backend/model `null`; timeout 2.0 s; `max_input_chars` 1500;
`only_when_ambiguous: true`; `allow_remote: false` (local only). It is consulted after the eligibility
filter, only for requests whose deterministic requirements are `ambiguous`, refines the task label only,
is skipped when its deployment is at capacity and held as uncertain on timeout. The four `explain`
dry-runs recorded `classifier: {}` (not consulted). The GX10's own value is UNKNOWN (config not readable);
nothing was enabled. Stage C design: `stage-b-plan.md` §6.

## K. Real client status

- Odysseus chat through ModelSaar on the GX10: **owner-reported working as of 2026-10-14** (reported in
  conversation). Not upgraded to tool, vision, streaming or agent workflow verification.
- Proposed additional client for Stage B / parallel validation: **Open WebUI** (the quickest to record
  per `site/VALIDATION.md`: Docker image, OpenAI connection to the gateway, model `auto`); nothing was
  installed or modified in Stage A.

## Decision records and dry-run routing (before the probes ran)

`raw/decisions.txt`: the 40 smoke requests through the Mac-local gateway (request id, requested
deployment, chosen deployment, outcome, routing overhead 0.2–0.4 ms, primary task). The four `explain`
dry-runs (`raw/explain-*.json`, `outcome: explain_only`, no inference, taken **before** `probe --all`, i.e.
with discovery-time capabilities and the assumed 4096 context):

| request | primary task | chosen | exclusions (reason) |
|---|---|---|---|
| plain chat | conversation | ollama/qwen3.8:latest | none |
| with a tool | agent | ollama/qwen3-coder:latest (`code` tag) | none |
| with an image | document_vision | ollama/qwen3.6-accurate:latest | muse-glimmer, qwen3.6, gemma4, qwen3.8: "effective context 4096 < required 4349 (input≈1277 + output 1024 + reasoning 2048)"; the two coder models: vision unsupported |
| strict JSON schema | extraction | **none** (`no_eligible`) | all eight: "json_schema is unknown (treated conservatively as not eligible)" |

Two routing consequences of the Stage A state are therefore on record: (1) until a model is observed
loaded, the assumed 4096 context excludes it from any request whose estimate exceeds 4096 (an image plus
the 2048 reasoning allowance already does); (2) strict-schema requests have no eligible deployment until
`json_schema` has been probed — after Stage A's `probe --all` both would resolve on the Stage A home, but
the GX10's own store has whatever its operator probed, which is NOT KNOWN here.

## What is NOT in this package

GX10 host facts (hardware, memory, storage, OS) — NOT EXPOSED; GX10 gateway state and config hash — NOT
OBSERVED/NOT READABLE; Tailscale path latency — NOT MEASURED; `/api/ps` context for six models — NOT
OBSERVED; prompts, keys — never recorded.
