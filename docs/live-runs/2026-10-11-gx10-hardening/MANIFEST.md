# Manifest — live run 2026-10-11 18:32–19:02 IST (hardening branch)

Everything needed to read, reproduce and audit this run. Companion to `README.md` (file index).

## Source revision

| item | value |
|---|---|
| tested revision | `0f8af84b66dfcca8f6e8de639a69fa9556f0f2a7` (`scripts: resumable one-command live verification …`), branch `hardening/review-2026-10-11` |
| branch head when published | `0172760…` + follow-ups. **Source difference between `0f8af84` and the branch head:** `src/modelsaar/evaluation/harness.py` only — the report's `deployments[]` entries additionally record `runtime_version`, `identity`, `endpoint`, `tags`, `memory_gb_estimate` (14 lines, no scoring/routing change). All other commits after `0f8af84` touch docs, scripts and this folder. The gateway, router, scorers and sandbox that produced these numbers are identical to the head. |
| ModelSaar version string | 0.1.0 (unreleased hardening branch) |
| working tree at run time | clean except untracked `.DS_Store` files and the run folder itself (`00-env.txt`) |

## Environment

| item | value |
|---|---|
| driver host | MacBook Air M5, macOS Darwin 27.0.0 arm64, CPython 3.12.15 (uv-managed) |
| inference host | ASUS GX10, Ollama **0.32.13** at `http://100.83.54.124:11434` (Tailscale) |
| isolation backend for `code_exec` | `sandbox-exec` (`/usr/bin/sandbox-exec`), reported in `30-eval-live.txt` and `eval-live.json → sandbox` |
| gateway | in-process gateway started by the evaluator on a free port; the verification gateway on port 27782 was stopped before the evaluation (`summary.txt`) |

## Commands (as executed by `scripts/live_verify.sh`, see `summary.txt` for exit codes)

```
modelsaar init --endpoint http://100.83.54.124:11434 --type ollama --port 27782 --force
modelsaar discover; modelsaar doctor
modelsaar probe --all --timeout 300                      # offline path (no gateway listening)
modelsaar explain … (4 dry runs)
modelsaar serve &  → /v1/models, modelsaar test, POST /admin/probe, scripts/live_client_checks.py, decisions, status
modelsaar eval --mode live --save-measurements --deployments qwen3.6:latest gemma4:31b qwen3-coder:latest \
    --out eval-live.json --checkpoint eval-live.json.records.jsonl --resume
modelsaar explain … ; modelsaar discover --json ; modelsaar doctor
```

## Configuration

`10b-config-redacted.txt` (API key redacted): loopback bind, `locality_mode: local_only`, one unified pool
`local-machine` with `max_concurrent: 1`, no memory budget set (`memory_gb` absent), one Ollama backend,
no operator overrides, default aliases (`auto` = profile `quality`), **classifier disabled**
(`routing.classifier.enabled: false`; `eval-live.json → routing.classifier = {used: 0, timeouts: 0}`),
default token estimate settings (`default_max_output 1024`, `reasoning_budget 2048` when a thinking-capable
deployment exists, `exact_count_deadline_s 1.5`).

## Deployments (identities)

| deployment | digest (identity) | params | quant | served ctx | evidence |
|---|---|---|---|---|---|
| ollama/qwen3.6:latest | `096fdbd02fe6…` (`02-backend-tags.txt`) | 35.5B | Q4_K_M | 4096 (assumed; unloaded) | fingerprint `f88be6aabf739d04` |
| ollama/gemma4:31b | `6316f0629137…` | 31.3B | Q4_K_M | 4096 (assumed) | fingerprint `0aa54db76e73f6fe` |
| ollama/qwen3-coder:latest | `06c1097efce0…` | 30.5B | Q4_K_M | 131072 (from `/api/show`) | fingerprint `04816854dbfe9f12` |

Capability evidence for all 8 discovered deployments: `13-probe-all.txt` (probe results with latencies
and notes) and `14-discover-after-probe.txt` (full registry JSON incl. `fingerprint_inputs`, catalogue
tags and memory estimates). Catalogue tags are hypotheses; `rules` is the only policy that uses them.

## Task set, scoring and evaluator

| item | value |
|---|---|
| task file | `src/modelsaar/evaluation/fixtures/tasks.jsonl` at `0f8af84` — 47 tasks, sha256 `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (`tasks_run_sha256 30027412804ea681…`) |
| split | 15 `calib` / 32 `test` (different templates; `fixtures/README.md`) |
| scorer version | `2026.10.11-2` (`src/modelsaar/evaluation/scoring.py`, rules in `fixtures/README.md`: `number` compares the last numeric token with tolerance; `tool_call` requires id + name + JSON-object args with all required keys + `args_contains`; `code_exec` requires exit 0, completion sentinel last, exact normalised stdout) |
| code-exec isolation | `sandbox-exec`; `code_exec` tasks scored, none skipped (`skipped: 0` in every policy) |
| request settings (all policies) | `temperature 0`, `max_tokens 400`, seed 7 (random baseline); no reasoning parameters are sent — thinking models spend their reasoning inside the same 400-token budget (this systematically penalises qwen3.6 and gemma4; a matched larger budget was **not** run) |
| evaluator | `src/modelsaar/evaluation/harness.py` at `0f8af84`; checkpoint/resume on; `resumed 0 record(s)` |

## Results, failures and violations

Aggregates: `eval-live.json` (`results`, `per_category`, `calibration`, `per_deployment_test`, `routing`).
Raw: `eval-live.json.records.jsonl` — 173 sanitised records (45 calib, 96 test sweep, 32 auto):
task id, category, split, policy, deployment, request id, HTTP status, latency, fingerprint, `ok`,
scorer detail, and for `auto` the decision fields (`overhead_ms`, `evidence`, `inferred_task`,
`classifier`, `violation`). No prompts, no model output, no keys.

Reproduce the aggregates from the raw records (checked: every number in `eval-live.json` matches):

```
python scripts/eval_aggregate.py docs/live-runs/2026-10-11-gx10-hardening/eval-live.json.records.jsonl \
                                 docs/live-runs/2026-10-11-gx10-hardening/eval-live.json
```

Exact comparison `auto` vs `fixed-strong` (qwen3-coder), from the records:

* success **30/32 each**. They differ on exactly two tasks: `vis-02` (image task) — `auto` routed it to
  gemma4 and passed, the fixed model returned 422 (capability violation); `long-01` — both used
  qwen3-coder, the fixed sweep's response passed and the `auto` run's response failed
  (`missing 'LINE 0: THE QUICK BROWN'`): run-to-run variation of the same model at temperature 0, not a
  routing difference. Both failed `math-05`.
* completion 32/32 vs 31/32; capability violations 0 vs 1 (the 422).
* end-to-end latency: p50 598 ms vs 639 ms; p95 7 958 ms vs 4 760 ms — the two `auto` requests to
  gemma4 took 16.6 s and 21.6 s. **Routing overhead** (decision time inside the gateway, separate from
  response latency): mean 0.67 ms, p95 0.98 ms, max 4.22 ms.
* n = 32; the 95 % Wilson intervals overlap for every pair of policies. Equal point estimates with
  overlapping intervals do not establish equivalence or superiority; the defensible statement is:
  *on this task set and hardware, automatic routing matched the strongest fixed model's task score,
  completed one more request (the image task), recorded no capability violation, and had a higher p95
  end-to-end latency.*

Failures per policy are the `ok: false` records; violations are `violation: true` records (one in each
qwen3-coder sweep: `vis-01`/`vis-02`).

## What this run did not do

Real client workflows (none installed; `50-real-clients.txt`), real-model embeddings, a generic
OpenAI-compatible backend, all 8 deployments, a matched reasoning budget, repeated runs for variance.
