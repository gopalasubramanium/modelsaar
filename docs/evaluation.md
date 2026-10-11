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
checks), `tool_call` (valid JSON arguments), `code_exec` (model code + harness in a disposable
`python -I` subprocess with time/memory limits). No LLM judge is used.

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

Live mode starts an in-process gateway from your config on a free port (your running instance is
untouched). The report records exact deployments (model, parameter size, quantization, runtime,
context, fingerprint), date, sample counts and every request's outcome.

## Acceptance targets for a reference configuration

Define before measuring; the harness reports against them.

| metric | target |
|---|---|
| capability violations (422 for requests a deployment could serve) under `auto` | 0 |
| completion rate under `auto` | ≥ fixed-strong |
| overall success under `auto` | ≥ fixed-strong − 0.05 (never materially worse than the best single model) |
| routing overhead (deterministic path) | p95 < 5 ms; with classifier < `classifier.timeout_s` |
| classifier timeouts | < 5 % of consulted requests |

## Result on the simulated configuration (2026-10-11, this build)

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
matches the oracle here only because it is handed the gold category label, which `auto` must infer. **This validates the harness and the policy mechanics only.** The fake backends
answer correctly by script when the task is in their `good_at` list, so the numbers say nothing about
real model quality. The identical procedure against real deployments is the NOT RUN item in the
[verification report](verification-report.md).

## Reporting rules

* Report per-category results with uncertainty; never a single universal "% better".
* If `auto` cannot beat a good fixed policy on your hardware, say so; the benefits may then be
  capability coverage (tools/vision/context across models), flexibility, or installation — and the
  simple mode (request a concrete deployment id) remains.
* Adaptive learning, bandits and online exploration are not part of 0.1 (roadmap).
