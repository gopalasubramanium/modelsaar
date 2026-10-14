# Stage A — frozen evaluation contract (read from the repository; nothing modified)

Frozen at repository `main` = `f18b2f195478d9a6591e7c637c321a46d9420e7e` (2026-10-14). Stage B must run the
harness **at this contract**; any change to the dataset, scorer or budgets is a separately authorised
experiment-design revision, not a Stage B step.

| item | value | source (file @ main, sha256 prefix) |
|---|---|---|
| Scorer version | `2026.10.12-3` | `src/modelsaar/evaluation/scoring.py` (`a06604e8…`), `SCORER_VERSION`; last changed in `be9bb49` (2026-10-12) |
| Dataset | `src/modelsaar/evaluation/fixtures/tasks.jsonl`, sha256 `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (unchanged since `182dd89`, 2026-10-11; the same file the published 2026-10-11 run recorded as `tasks_file_sha256`) | fixtures (`84c34596…`) |
| Task count | 47 | counted |
| Split | `calib` 15 / `test` 32; different templates per split (fixtures README) | counted |
| Categories (calib/test) | conversation 2/5, coding 2/5, agent 2/4, math 2/6, extraction 2/2, summarization 1/3, translation 1/2, rag 1/2, decision 1/2, document_vision 1/1 | counted |
| Scorer types (count) | contains_any 13, contains 9, number 6, nonempty 5, code_exec 5 (calib 2 / test 3), tool_call 5 (2/3), json_schema 4 (2/2) | counted |
| Request budget | `temperature 0`, `max_tokens 400` (`harness.py` `MAX_TOKENS`, `TEMPERATURE`); identical body for every policy | `src/modelsaar/evaluation/harness.py` (`eca0a0f0…`) |
| Seed | default `7` (`EvalRun(seed=7)`, `--seed`); affects only the random baseline | harness.py |
| Checkpoint format | `CHECKPOINT_FORMAT = 2`: one sanitised JSONL record per request keyed by (policy, task) with `task_sha256` and a `conditions_key` over scorer version, max_tokens, temperature, seed (random only), routing config hash and `eligible_set_key` (sorted ids + fingerprints); a record whose key no longer matches is re-run and counted under `resume_rejected`; prompts are never written | harness.py `conditions_key`, `eligible_set_key` |
| Code-execution sandbox | `code_exec` tasks run only under bubblewrap (Linux), `sandbox-exec` (macOS — **disabled in the alpha** unless `MODELSAAR_MACOS_SANDBOX=verify`) or Docker (`--network none --read-only`); otherwise the task is **skipped** and reported, never run on the host | `src/modelsaar/evaluation/sandbox.py` (`6023c12b…`), `scoring.py` |
| Capability requirements | tasks carry `tools` (6 tasks) / image parts (2 tasks) / `response_format`; the gateway's eligibility filter applies equally to every policy; a `422` from the gateway is recorded as a capability violation (`rec["violation"]`) | harness.py L292, L349 |
| Routing-overhead measurement | for `auto` only: `overhead_ms` read from the decision record of each request (`/admin/decisions/<id>`); report gives mean and p95 | harness.py L320, L565–568 |
| fixed-strong rule | the deployment with the highest **calibration** success, ties broken by lower p50 latency: `max(dep_ids, key=(success, -p50_ms))` | harness.py L511 |
| fixed-fast rule | the deployment with the lowest **calibration** p50 latency | harness.py L512 |
| oracle | a test task counts as solvable if **any** deployment solved it in the test sweep (offline upper bound; labelled "not available at runtime") | harness.py L539–547 |
| rules baseline | deterministic specialist mapping **given the gold category label**: coding/agent → first deployment tagged `code` (else strong); document_vision → first vision-supported; math/extraction/rag → strong; otherwise fast | harness.py `rules_policy` L383–395 |
| random baseline | seeded uniform choice over the eligible deployments (diagnostic) | harness.py |
| auto | live routing through the harness's own in-process gateway on the test split, same eligibility checks and budgets | harness.py |
| Classifier fields (if enabled later) | `routing.classifier.{enabled, backend, model, timeout_s=2.0, max_input_chars=1500, only_when_ambiguous=true, max_output_tokens=64, allow_remote=false}`; consulted after eligibility, only when the deterministic requirements call the task `ambiguous`; it refines the task label only; skipped when its deployment is at capacity; its slot is held as uncertain on timeout | `src/modelsaar/config.py` `ClassifierConfig`; `routing/router.py` L334–359; `routing/classifier.py` `should_run` |
| Live-gateway detection | `run_live` refuses to start when a ModelSaar gateway (or another process) listens on the configured `server.host:port` unless `--allow-concurrent`; the evaluation then runs its own in-process gateway on a free port with its own admission | harness.py L718–731 |

## Confirmation: no held-out task was used to tune routing in Stage A

Stage A sent no evaluation task to any model. The only requests were ModelSaar's capability probes
(`probe --all`: fixed probe prompts) and the four smoke prompts in `smoke-metrics.json`, none of which
is a `tasks.jsonl` task. No routing weight, profile, prior, tag or alias was changed.

## Ambiguities found in Stage A (documented; not altered)

1. **Reasoning budget.** With `max_tokens` 128–200, the thinking models (`muse-glimmer`, `qwen3.6`,
   `qwen3.6-accurate`, `qwen3.6-fast`, `gemma4`) returned `finish_reason: length` with **no content**
   on the JSON-object and counting prompts (their reasoning consumed the budget); the non-thinking
   coder models and `qwen3.8` answered. The frozen harness budget is `max_tokens 400`, under which the
   2026-10-11 run did obtain answers from `qwen3.6`/`gemma4`, but the backlog item "evaluation with a
   reasoning-matched budget" stands: Stage B results for thinking models are conditional on that budget
   and must be read as such. Changing the budget is an experiment-design revision, not a Stage B tweak.
2. **Served context vs assumed context.** ModelSaar at `cf56cdd` assumes 4096 tokens of served context
   for models without a Modelfile `num_ctx` until it observes the model loaded in `/api/ps`. Ollama
   0.40.3 reported `context_length` 131072 for `qwen3.8` once loaded. Stage B's context-size eligibility
   therefore depends on whether each model has been observed loaded during the run (see
   `deployments.json` and `stage-b-plan.md` §2). This is the documented assumption, not a defect.
3. **Capability declared vs measured.** `qwen3.6-fast` is declared `tools` by Ollama but the probe
   measured `unsupported` (no `tool_calls` returned); `muse-glimmer` is declared `vision` but the probe
   measured `unsupported` (answer did not identify the colour). The harness uses the probed values
   (`--probe`), so these two deployments will be excluded from tool / vision tasks respectively.
