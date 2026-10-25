# CLASSIFIER OFF vs ON: COMPLETE WITH LIMITATIONS (2026-10-25, Ollama 0.40.5) — outcome: KEEP OFF

This is the optional classifier comparison of `docs/plans/measured-routing-quality.md` (design item 5) as
prepared in `../2026-10-14-gx10-stage-a/stage-b-plan.md` §6: the Stage B Pass 1 pool (qwen3.8, qwen3-coder,
gemma4:31b, qwen3.6), the frozen harness, tasks, budgets and seed, with the live classifier **enabled**
(`backend: ollama`, `model: qwen3.8:latest`, `timeout_s 2.0`, `only_when_ambiguous: true`) and compared with
the deterministic router. Owner-authorised 2026-10-25 03:23 IST; executed **03:28:46–04:08:41 IST** as one
launcher run of two evaluations: an OFF twin (same session, same runtime; **compromised**, see below) and the
ON run (**complete**, 03:30:26–04:08:39 IST, 2293 s, exit 0, watchdog not triggered).

**Decision rule (predeclared):** the classifier stays off unless its success gain on the held-out split is
positive with the 95 % interval excluding zero *and* the median routing overhead stays under 250 ms.
**Result: gain 0.000 (30/32 vs 30/32, no discordant task, interval [0, 0]); median overhead 0.55 ms. The
first condition fails → KEEP OFF; the simpler router is retained.** No routing change follows.

## What was compared, and against what

- **ON** = `on/classifier-on.json` (config hash `58fe0f31907b03ae`; differs from the OFF config by exactly three
  lines: `enabled: true`, `backend: ollama`, `model: qwen3.8:latest`). Resumed 0; never resumed from any earlier
  checkpoint (different hash by design).
- **OFF reference** = Stage B **Pass 1b** `auto` (`../2026-10-15-gx10-stage-b-pass1/stage-b-pass1b.json`, the
  owner-accepted Pass 1 result), exactly as §6 defines it ("OFF = Stage B pass 1 `auto` result"). Pass 1b ran on
  **Ollama 0.40.3**; the ON run on **0.40.5** with the re-created `qwen3.6:latest` tag (same weights). **The
  ON-vs-OFF comparison is therefore cross-runtime**, like every comparison with Pass 1b since 2026-10-16.
- **OFF twin (compromised, preserved)** = `off-compromised/classifier-off.json`: the launcher first re-ran the OFF
  configuration (hash `c58ce04fa1ed9902`) in the same session to obtain a same-runtime reference. After 11
  calibration requests (all HTTP 200, 03:28:59–03:29:44) the gateway's backend health refresh failed with
  `ollama: ConnectTimeout` (Mac → GX10 over Tailscale), every deployment was marked unhealthy from 03:29:49, and
  the remaining **209 requests all returned HTTP 422 `no_eligible_deployment`** within 36 s — the frozen harness
  has no back-off while the backend is unhealthy. The ON run started 60 s later against a healthy backend (453
  sidecar samples, 0 unhealthy). Per the owner's standing rule (one evaluation, no rerun for health issues,
  preserve partial evidence) the twin was **not** rerun; it is labelled compromised and contributes nothing to
  the rule. Its report reproduces from its records (`scripts/eval_aggregate.py`), all policies 0/32.

## Held-out results — ON run (32 tasks; Wilson 95 % intervals; reproduced from the records)
| policy | success | 95 % CI | completion | violations | p50 | p95 |
|---|---|---|---|---|---|---|
| **auto** (router + classifier) | **0.938** (30/32) | [0.799, 0.983] | 1.000 | 0 | 418 ms | 23046 ms |
| fixed-strong (qwen3.8) | 0.938 (30/32) | [0.799, 0.983] | 1.000 | 0 | 3010 ms | 30514 ms |
| fixed-fast (qwen3-coder) | 0.938 (30/32) | [0.799, 0.983] | 0.969 | 1 | 458 ms | 23122 ms |
| rules (gold-category diagnostic) | 0.844 (27/32) | [0.682, 0.931] | 1.000 | 0 | 2328 ms | 26307 ms |
| random (seeded diagnostic) | 0.719 (23/32) | [0.546, 0.844] | 1.000 | 0 | 4201 ms | 31747 ms |
| oracle (offline upper bound) | 1.000 (32/32) | [0.893, 1.0] | 1.000 | 0 | 456 ms | 23122 ms |

Calibration chose fixed-strong **qwen3.8** (15/15) and fixed-fast **qwen3-coder** (p50 490 ms) — the same two
as Pass 1b, Pass 2 and Stage C. Test sweeps: qwen3.8 0.938, gemma4 0.938, qwen3-coder 0.938 (1 violation,
`vis-02`), qwen3.6 0.594. The only non-200 records are the two declared vision exclusions on qwen3-coder.

## ON vs the OFF reference (Pass 1b), task by task
- **Outcomes identical on all 32 tasks**: both fail `math-05` and `long-01`, both pass the other 30. Paired
  difference 0.000, no discordant task. Per-category successes identical (math 5/6, summarization 2/3, all else
  full).
- **Selection identical**: qwen3-coder on 31 tasks, qwen3.8 on `vis-02`. Inferred task labels identical
  (task-label accuracy 0.844 in both; routing mistakes `math-05`, `long-01` in both).
- **The classifier never produced a label.** It was consulted on exactly the six tasks the deterministic
  requirements flag ambiguous (`ambig-01`, `ambig-02`, `code-06`, `math-06`, `sum-02`, `sum-03`) and **timed out
  on all six** (status `timeout`, 2002–2004 ms each; `used: 0`). Gateway-wide the classifier made **38 calls
  (every ambiguous request of every policy, calibration and test), 38 timeouts, 0 other failures.** With
  `used = 0`, ON could only ever reproduce OFF's labels and choices, which it did.
- **Overhead**: ON mean 376.09 ms, **median 0.55 ms**, p95 2003.52 ms, max 2004.47 ms (26 skipped tasks:
  0.18–3.32 ms; six timeouts: ≈ 2003 ms). Pass 1b: mean 0.37 ms, median 0.26 ms, p95 0.47 ms. The median
  passes the 250 ms bound only because the classifier was skipped on 26 of 32 tasks.
- **Classifier model residency**: `qwen3.8:latest` was resident with `size_vram` 18 798 597 897 bytes (18.8 GB)
  in every `/api/ps` snapshot (before the OFF twin, between the runs, after the ON run); the timeouts were not
  cold loads.

## An unexpected cost the records show (descriptive; cause not established)
On the six consulted tasks, end-to-end latency in the ON run was **≈ 22 s higher than in Pass 1b for every
policy and every deployment** — e.g. `math-06` on qwen3-coder 130 ms → 22 139 ms, on qwen3.6 4.2 s → 26.2 s, on
gemma4 29.7 s → 52.6 s; under `auto` 99 ms → 22 182 ms — while the 26 non-ambiguous tasks shifted by a median of
+3 ms (p10/p90 −165/+487 ms across all 130 fixed-sweep pairs). The decision records put only 2.0 s of that in
`overhead_ms` and ~0.2 s in the upstream call (`outcome_detail` "172ms" for `math-06`); the remaining ≈ 20 s is
not attributed by any field the frozen harness records. The classifier request is cancelled client-side at
2.0 s, but nothing in the evidence shows whether the backend kept generating the orphaned classifier response
(qwen3.8 is a thinking model and the request does not disable thinking) and whether that stalled the following
request at the gateway's admission or at Ollama's scheduler. **This is a hypothesis for a follow-up, not a
finding**; it is why the ON p95 columns (23–31 s) are far above Pass 1b's (1.8–10 s) for all policies, and it is
a second reason — besides the decision rule — not to enable this configuration.

## Acceptance against the predeclared targets (`acceptance.md`)
capability violations 0 **PASS** · completion 1.000 ≥ 1.000 **PASS** · success 0.938 ≥ 0.888 **PASS** ·
routing overhead with classifier p95 < `timeout_s` (2000 ms): 2003.52 ms **FAIL (marginal)** · classifier
timeouts < 5 % of consulted: 100 % (6/6; 38/38 gateway-wide) **FAIL** · decision rule → **KEEP OFF**.
Disposition unchanged (1 — deterministic routing baseline accepted, decided on Pass 1b).

## Material limits (read before quoting)
1. **No same-runtime OFF reference.** The OFF twin is compromised (health flap); the rule is evaluated against
   Pass 1b (Ollama 0.40.3) → cross-runtime. Because outcomes, labels and selections are identical and the
   classifier produced no label, the runtime confound cannot have changed the rule's verdict, but it does
   confound every latency comparison between the two.
2. **The classifier was never effective**: 38/38 timeouts at 2.0 s with the model resident. This run therefore
   measures the *cost of consulting* this classifier configuration, not the *value of its labels*. §6 named
   `qwen3-coder` as the non-thinking alternative; it was not run (one authorised run, contract unchanged).
3. **≈ 20 s unattributed stall per consulted request** (above) — mechanism not established by the records.
4. **n = 32**, six ambiguous tasks; equal point estimates do not establish equivalence.
5. **Health flap**: a single `ConnectTimeout` in the gateway's refresh marked all deployments unhealthy and the
   harness burned through 209 requests in 36 s without back-off — a harness limitation worth a backlog entry;
   no code was changed here.
6. **Production gateway not observed** (placement A never contacts it); DERP-relayed Mac→GX10 path in every
   latency column equally; stored measurements unchanged (133 rows; no `--save-measurements`).

## Evidence
Folder `docs/live-runs/2026-10-25-gx10-classifier-comparison/` (`MANIFEST.md`, `comparison.json` with the per-task
table and the rule evaluation). Canonical Mac run files: ON report sha256
`1b51d8cf7346bb2dbee1c665742f7d9c9f61e0ec3eca1527b47ac445f1d7980e`, ON checkpoint
`e67d7cb575bcae5081e3d09be50c0c6b24af01c13d73f1c1b8594f7f2a8d8f26`; OFF twin report
`7fdc1ba4c81df06f8196b3192d2fc8bc84201473efc22ca2e05bd784e4c9c959`, checkpoint
`ddaa12c54872691329fdf42127c0da2c5a9e31a0dd3ffab4f587be3bceb85b08`. Public report copies are path-redacted and
equal the canonical objects once the placeholders are restored (verified); checkpoints byte-identical.
`scripts/eval_aggregate.py`: "all aggregates in the report match the records" for both runs (see `MANIFEST.md` §E
for the display-line caveat on the all-422 twin).

## STOP — confirmed
No Ollama, GX10 service, model-tag, registry, evaluator, scorer, routing or production-configuration change;
the OFF `config.yaml` (hash `c58ce04fa1ed9902`) untouched before and after; Pass 1/1b/2 and Stage C evidence
unchanged (hashes verified before and after); no website publication; no merge; no sensitivity run, no routing
tuning, no release.
