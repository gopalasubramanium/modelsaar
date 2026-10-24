# Evaluation: does intelligent routing help?

`modelsaar eval` is an executable harness that compares `auto` against strong fixed policies on a
compact, inspectable task set with executable or exact scoring. It reports per-category results with
95 % Wilson intervals, completion rate, capability violations, latency and routing overhead.

## Task set

`src/modelsaar/evaluation/fixtures/tasks.jsonl`: 47 original synthetic tasks (Apache-2.0, no
third-party data) across conversation, coding, agent/tools, math, extraction (strict schema),
summarization, translation, RAG-style, decision, vision, a tool round trip, mixed-language and
deliberately ambiguous prompts, plus a long-but-easy transformation. Splits: `calib` (15) and `test`
(32) use different templates. Scorers: `nonempty`, `contains`, `contains_any`, `json_schema` (+field
checks), `tool_call` (strict: non-empty id, expected name, JSON-object arguments that conform to the
tool's declared parameter schema, contain every required parameter and the expected substrings),
`code_exec` (a trusted runner executes the model code with its stdout captured, then the task
harness with *its* stdout captured, and writes a result record keyed with a per-run nonce; the task
passes only when that record says the harness completed and the harness output equals the
expectation — text the model prints, including any "completion marker", is never evidence). `code_exec`
runs **only** under bubblewrap (Linux; only the Python runtime and system libraries are visible),
`sandbox-exec` (macOS; deny-by-default profile with runtime read roots — **unsupported in this alpha
pending verification**: disabled unless `MODELSAAR_MACOS_SANDBOX=verify`, so on macOS `code_exec`
tasks are skipped and the report says why) or Docker (`--network none --read-only`) with
CPU/memory/output/time limits; without one of those the task is skipped and the report says so —
there is no host-execution fallback. The sandbox is tested for writes, network,
timeouts and reading a synthetic host file outside the work directory; it does not defend the
evaluator against model code that targets the evaluator process itself. Scorer rules are versioned
(`SCORER_VERSION`) and recorded in the report's `conditions`; checkpoint records (`--checkpoint`,
`--resume`) are bound to the task content, the scorer version and request budgets, the routing
configuration and the eligible deployment set (for routed policies: a new, removed or re-identified
alternative re-runs the task) and the deployment fingerprint, and anything that no longer matches is
re-run and counted under `resume_rejected` instead of being attributed to the new run. `--probe`
runs the capability probes through the gateway's admission, one reservation per deployment; after an
uncertain timeout the reservation is held and the remaining deployments are reported `deferred`
rather than probed on top of work that may still be running.
No LLM judge is used. See `src/modelsaar/evaluation/fixtures/README.md` for the exact rules.

## Procedure

1. Probe every local generative deployment (`streaming`, `tools`, `json_object`, `json_schema`,
   `vision`) so capability evidence is real, not declared.
2. Sweep the calib split over every deployment → per-deployment quality/latency. This calibrates
   the **fixed-strong** (best calib success) and **fixed-fast** (lowest calib p50) baselines and, with
   `--save-measurements`, becomes routing evidence keyed by fingerprint.
3. Sweep the test split over every deployment → per-deployment results and the **oracle** (a task
   counts as solvable if any deployment solved it; an offline upper bound, unavailable at runtime).
4. Run **auto** live through the gateway on the test split (routing overhead measured per request
   from the decision record).
5. Derive **rules** (deterministic specialist mapping that is *given the gold category label*, an
   advantage auto lacks) and **random** (seeded) from the test sweep.

All policies send identical requests through the same HTTP gateway with the same eligibility checks
and budgets (`temperature 0`, `max_tokens 400`).

## Running

```bash
modelsaar eval --mode simulated                 # no models needed; validates mechanics only
modelsaar eval --mode live --probe --save-measurements --out eval-$(date +%F).json
```

Live mode starts an in-process gateway from your config on a free port. Because that gateway's
admission cannot coordinate with another instance using the same backends, the run refuses to start
while a gateway listens on the configured port unless you pass `--allow-concurrent`. Long runs are
resumable: `--checkpoint PATH` (default `<out>.records.jsonl` with `--out`) appends one sanitised
record per request (ids, status, latency, scorer detail — never prompts), and `--resume` skips
recorded tasks whose deployment fingerprint is unchanged. The report records exact deployments
(model, parameter size, quantization, runtime, context, fingerprint, endpoint), the conditions
(`max_tokens`, temperature, seed, scorer version, git commit, sandbox backend, dataset revision),
date, sample counts and every request's outcome. `scripts/live_verify.sh` wraps probes, wire-level
client checks and this evaluation into one resumable command.

## Acceptance targets for a reference configuration

Define before measuring; the harness reports against them.

| metric | target |
|---|---|
| capability violations (422 for requests a deployment could serve) under `auto` | 0 |
| completion rate under `auto` | ≥ fixed-strong |
| overall success under `auto` | ≥ fixed-strong − 0.05 (never materially worse than the best single model) |
| routing overhead (deterministic path) | p95 < 5 ms; with classifier < `classifier.timeout_s` |
| classifier timeouts | < 5 % of consulted requests |

## Results — read the label before the table

Every table below is tied to a scorer version and a source revision. The current scorer is
`2026.10.12-3` (record-based `code_exec` completion evidence, tool-argument schema validation; see
"Scorers" above). **One live evaluation has been run under the current scorer — Stage B Pass 1, 2026-10-15 (`live-runs/2026-10-15-gx10-stage-b-pass1/`), accepted by the owner on 2026-10-16; a second run, Stage B Pass 2 (`live-runs/2026-10-16-gx10-stage-b-pass2/`, Ollama 0.40.5, five deployments), followed the same day and is labelled cross-runtime relative to Pass 1; Stage C (`live-runs/2026-10-24-gx10-stage-c/`, Ollama 0.40.5, all eight deployments) completed the roadmap's deployment stages on 2026-10-24; the optional classifier OFF/ON comparison (`live-runs/2026-10-25-gx10-classifier-comparison/`, Ollama 0.40.5, Stage B Pass 1 pool) ran on 2026-10-25 and kept the classifier off (no label produced — 38/38 timeouts at 2 s; outcomes identical to Pass 1b; targets 4 and 5 of the table above FAIL for that configuration). The owner-approved website update (2026-10-24) quotes the accepted Pass 1b result, the cross-runtime Pass 2 result and Stage C with their caveats; it is a separate site change.** Before it, only the simulated smoke had run under this scorer (it validates mechanics, not model quality). The numbers below were
produced by the scorer named next to them and are kept as recorded; they are not relabelled, and a
rerun — when it happens — will be reported as a separate run with its own scorer version.

**Current reference result:** the GX10 run of 2026-10-11 at source `0f8af84` (scorer `2026.10.11-2`,
3 deployments, 32 test tasks): `auto` and the strongest fixed model each 30/32; `auto` completed
32/32 vs 31/32 and recorded 0 vs 1 capability violations; reported end-to-end p95 7.958 s vs 4.760 s;
routing overhead p95 0.98 ms (a separate quantity). The `long-01` difference occurred on the same
model and its cause has not been isolated; the live classifier was disabled. Full manifest, exact
comparison and the 173 sanitised records: `live-runs/2026-10-11-gx10-hardening/MANIFEST.md` (the
aggregates reproduce from the records with `scripts/eval_aggregate.py`; the run has
`resumed_records = 0`). This is the result the website quotes.

### Historical: simulated configuration (2026-10-11, source `c26ee44` — before scorer versioning)

Three scripted fake deployments (`sim-small:1b`, `sim-code:7b` tagged `code`, `sim-large:27b` with
vision/thinking), 15 calib / 32 test tasks, seed 7:

| policy | success | 95 % CI | completion | violations |
|---|---|---|---|---|
| auto (live routing) | 0.938 | [0.80, 0.98] | 1.00 | 0 |
| fixed-strong (calibrated: sim-large) | 0.719 | [0.55, 0.84] | 1.00 | 0 |
| fixed-fast (calibrated: sim-small) | 0.438 | [0.28, 0.61] | 0.97 | 1 |
| rules (gold label + specialist tags) | 0.969 | [0.84, 0.99] | 1.00 | 0 |
| random | 0.469 | [0.31, 0.64] | 0.97 | 1 |
| oracle (upper bound) | 0.969 | [0.84, 0.99] | 1.00 | 0 |

Routing overhead mean 0.43 ms, p95 0.52 ms; deterministic task-label accuracy 0.84; one routing
mistake (`math-06`, "Is 97 a prime number? Answer yes or no." — classified as ambiguous between
math and decision; with only two calibration samples per category the blended quality difference did
not outweigh the resident small model's latency/residency advantage). The rules baseline
matches the oracle here only because it is handed the gold category label, which `auto` must infer.
**This validates the harness and the policy mechanics only.** The fake backends answer correctly by
script when the task is in their `good_at` list, so the numbers say nothing about real model quality.
(CI re-runs a simulated smoke on every push; its numbers change with the scorer and are not quoted.)

### Historical: first real-hardware run (GX10 / Ollama 0.32.13, 2026-10-11, source `1122e1f`, scorer before versioning)

Superseded by the current reference result above; kept because the bugs it exposed are the subject
of the 2026-10-11 review (F01–F18). 3-deployment subset:

| policy | success | 95 % CI | completion | violations | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| auto (live routing) | 0.875 | [0.72, 0.95] | 1.000 | 0 | 693 | 27 136 |
| fixed-strong (qwen3-coder) | 0.906 | [0.76, 0.97] | 0.969 | 1 | 646 | 4 849 |
| fixed-fast (qwen3-coder) | 0.906 | [0.76, 0.97] | 0.969 | 1 | 646 | 4 849 |
| rules (gold label) | 0.812 | [0.65, 0.91] | 1.000 | 0 | 959 | 4 868 |
| random | 0.688 | [0.51, 0.82] | 0.938 | 2 | 4 189 | 9 826 |
| oracle | 0.969 | [0.84, 0.99] | 1.000 | 0 | 552 | 4 585 |

In that run `auto` did not match the best fixed model (it mostly chose that model); its measurable
gains were coverage (no capability violations, 100 % completion) at the price of p95 latency when a
thinking model was selected. Context and the defects it exposed: [verification-report.md](verification-report.md).

## Reporting rules

* Report per-category results with uncertainty; never a single universal "% better".
* If `auto` cannot beat a good fixed policy on your hardware, say so; the benefits may then be
  capability coverage (tools/vision/context across models), flexibility, or installation — and the
  simple mode (request a concrete deployment id) remains.
* Adaptive learning, bandits and online exploration are not part of 0.1 (roadmap).
