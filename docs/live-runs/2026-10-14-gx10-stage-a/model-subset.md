# Stage A — representative Stage B model subset and baseline candidates

Evidence: `deployments.json` (identity, context), `capabilities.json` (probe results), `smoke-metrics.json`
(low-cost characterisation), the 2026-10-11 live evaluation (`docs/live-runs/2026-10-11-gx10-hardening/`,
three deployments, scorer `2026.10.11-2`, Ollama 0.32.13 — historical, not comparable with Stage B).
No quality conclusion is drawn from the smoke prompts.

## The eight deployments at a glance (measured 2026-10-14, Ollama 0.40.3)

| deployment | family / arch | params · quant · weights | probed capabilities | thinking | warm chat p50 (smoke) | cold load est. | notes |
|---|---|---|---|---|---|---|---|
| ollama/qwen3.8:latest | qwen35 (dense) | 27.3B · Q4_K_M · 17.7 GB | stream, tools, parallel tools, json_object, json_schema, vision | yes (declared) | 1.0 s | n/a (resident) | answered every smoke prompt; served context 131072 observed in `/api/ps` |
| ollama/qwen3.6:latest | qwen35moe | 35.5B · Q4_K_M · 22.6 GB | all six | yes | 1.3 s | ~7.6 s | reasoning exhausted the 128/200-token smoke budgets (no content) |
| ollama/qwen3.6-accurate:latest | qwen35moe | 36.0B · Q4_K_M · 23.9 GB | all six | yes | 1.6 s | ~7.5 s | Modelfile `num_ctx 131072`; same family/size as qwen3.6; same budget behaviour |
| ollama/qwen3.6-fast:latest | qwen35moe | 36.0B · Q4_K_M · 23.9 GB | stream, json_object, json_schema, vision; **tools unsupported (measured)** | yes | 1.6 s | ~7.2 s | Modelfile `num_ctx 65536`; not faster than qwen3.6 on the smoke set |
| ollama/gemma4:31b | gemma4 | 31.3B · Q4_K_M · 19.9 GB | all six | yes | 4.6 s | ~8.1 s | slowest warm chat; strongest non-Qwen general model available |
| ollama/muse-glimmer:latest | muse-glimmer | 27.9B · Q4_K_M · 18.2 GB | stream, tools, parallel tools, json_object, json_schema; **vision unsupported (measured)** | yes | 7.1 s | ~6.6 s | slowest warm chat of all; declared vision not reproduced |
| ollama/qwen3-coder:latest | qwen3moe | 30.5B · Q4_K_M · 18.6 GB | stream, tools, parallel tools, json_object, json_schema; vision unsupported (declared) | no | 0.11 s | ~6.6 s | fastest; tagged `code`,`agent` by ModelSaar; the coding specialist |
| ollama/qwen3-coder-next:latest | qwen3next | 79.7B · Q4_K_M · 51.7 GB | same as qwen3-coder | no | 0.14 s | ~12.8 s | largest weights (2.8× qwen3-coder); untagged (uncalibrated prior) |

## Selected Stage B subset (5 deployments)

| included | why it adds experimental value |
|---|---|
| **ollama/qwen3.8:latest** | the model `auto` selected on the GX10 after the 2026-10-14 upgrade (owner-reported); dense 27B general model with every capability measured supported and served context observed at 131072; fastest warm chat among the thinking models |
| **ollama/qwen3-coder:latest** | the coding/agent specialist the `rules` baseline and the `auto-code` alias rely on (`code` tag); non-thinking, fastest end-to-end; the only way to measure whether routing coding/agent tasks to a specialist pays |
| **ollama/gemma4:31b** | the only non-Qwen general model; distinct family, distinct speed profile (slowest thinking general model), all capabilities probed supported — tests whether evidence-based ranking avoids a capable-but-slow model where speed matters |
| **ollama/qwen3.6:latest** | in the 2026-10-11 run (calibration success 0.467 at `max_tokens 400`, p50 4.3 s) — keeps continuity with the published result and gives a MoE thinking general model next to the dense qwen3.8; the pair the router must separate on evidence rather than name, and the clearest test of the reasoning-budget hazard |
| **ollama/qwen3-coder-next:latest** | the largest model on the machine (80B MoE, 52 GB weights, ~13 s cold load) with the same capability profile as qwen3-coder: the residency/loading cost case the router's `residency` weight exists for. Included only in a second pass if the stage A budget allows (stage-b-plan.md §4); otherwise deferred with the reason below |

## Excluded / deferred

| deferred | reason (evidence) |
|---|---|
| ollama/qwen3.6-accurate:latest | same family, size and quantization as qwen3.6 (qwen35moe 36B Q4_K_M), same probe profile, same smoke behaviour; differs only by Modelfile `num_ctx 131072` — a near-duplicate; keep for a later context-size experiment |
| ollama/qwen3.6-fast:latest | same family/size as qwen3.6; **not** faster in the smoke set (1.6 s vs 1.3 s warm); tools measured unsupported, so it would be ineligible for the 6 tool tasks — slower duplicate with a smaller capability set |
| ollama/muse-glimmer:latest | slowest warm chat (7.1 s); declared vision not reproduced by the probe; catalogue prior only — insufficient distinct value for a first measured pass; candidate for a later "vision/agent" experiment once its vision behaviour is understood |

Nothing is deleted or disabled; production availability of all eight is unchanged.

## Baseline candidates (nominated, not crowned — Stage B's calibration split decides)

- **Historical evidence (2026-10-11, scorer `2026.10.11-2`, Ollama 0.32.13, three deployments):** the
  calibration sweep made `ollama/qwen3-coder:latest` **both** fixed-strong (0.933 success, p50 0.68 s) and
  fixed-fast; `gemma4:31b` 0.80 (p50 17.8 s) and `qwen3.6` 0.467 (p50 4.3 s) — the thinking models lost
  calibration tasks under the 400-token budget. That run did not include `qwen3.8`.
- **fixed-strong candidates:** `ollama/qwen3-coder:latest` (historical winner), `ollama/qwen3.8:latest`
  (every capability measured supported; the only thinking model that answered all smoke prompts inside
  small budgets; untested by the harness so far) and `ollama/gemma4:31b` (historical 0.80). The harness
  rule (max calibration success, then lower p50) decides among whatever is in the Stage B pool.
- **fixed-fast candidates:** `ollama/qwen3-coder:latest` (historical winner; warm chat 0.11 s, 60 chunks/s
  in the smoke set) and, if included, `ollama/qwen3-coder-next:latest` (0.14 s warm). `qwen3.8` (1.0 s) is
  the fastest thinking model but not expected to beat a non-thinking coder on calibration p50.
- Not decided here: whether any thinking model beats `qwen3-coder` on calibration success at
  `max_tokens 400` — that is the calibration sweep's job and must not be read from the test split.
