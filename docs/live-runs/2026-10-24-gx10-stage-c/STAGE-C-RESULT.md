# STAGE C: COMPLETE (2026-10-24, Ollama 0.40.5) — all eight roadmap deployments, classifier off

Stage C is the eight-deployment run of `docs/plans/measured-routing-quality.md` (design item 3): the same
frozen harness and contract as Stage B, with every generative model the roadmap names on the GX10 in the
eligible pool. The classifier stayed **off** (the "classifier ON" design in `stage-b-plan.md` §6 would be
a routing-policy change and was not run). One run, owner-authorised 2026-10-24 01:09 IST, executed
**07:32:56–08:28:33 IST (3337 s, exit 0)** inside the two-hour window; watchdog not triggered.

**How this relates to the earlier runs.** Pass 1b (accepted Stage B Pass 1) ran on Ollama **0.40.3**;
Pass 2 and Stage C ran on **0.40.5**. Any comparison with Pass 1b is therefore **cross-runtime**. Pass 2
added `qwen3-coder-next` and **never selected it (0/32)**; because the runtime, the `qwen3.6:latest` tag
and the pool changed at once, Pass 2 **did not isolate** the effect of adding that model. Pass 1, Pass 1b
and Pass 2 evidence is unchanged (hashes verified by this launcher before and after).

## Execution
- Placement A as in every earlier run: the harness's in-process gateway on the Mac (Stage A home), backend the
  GX10's Ollama over Tailscale. **`modelsaar.service` on the GX10 was not stopped and not touched** — placement A
  does not require it; its `/healthz` on both addresses answered HTTP 000 (unreachable from the Mac) before and
  after, as in Stage A, so the production service's state is recorded as NOT OBSERVED from the Mac.
- Runtime **Ollama 0.40.5** before and after (recorded; the same as the 2026-10-16 re-baseline and Pass 2).
- Frozen elements: evaluator checkout `cf56cdd3416d8c853b64111b9b40211e5b126031` (clean); scorer `2026.10.12-3`;
  tasks sha256 `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (15 calibration + 32 held-out);
  max_tokens 400, temperature 0, seed 7; routing config hash `c58ce04fa1ed9902`; classifier disabled (consulted 0);
  `sandbox-exec` (5 `code_exec` tasks executed in isolation); `--probe --save-measurements`; resumed 0.
- **Eight deployments** (`--deployments`): qwen3.8, qwen3.6, qwen3.6-fast, qwen3.6-accurate, qwen3-coder,
  qwen3-coder-next, gemma4:31b, muse-glimmer. All eight discovered and healthy; **identities equal the 0.40.5
  re-baseline (8/8)**; vs Stage A only `qwen3.6:latest`'s manifest digest differs (tag re-created 2026-10-16, same
  weight blobs). Inventory on the GX10: 11 tags (unchanged since 2026-10-16); the `--probe` step probed 9
  generative deployments (8 + `d1`).
- 408 records = 120 calibration + 256 test + 32 auto: **402 × HTTP 200, 6 × HTTP 422** — the vision tasks
  `vis-01`/`vis-02` refused on the two coder models (declared) and on **muse-glimmer**, whose live vision probe
  returned *unsupported* although Ollama declares vision ("image accepted but answer did not identify the
  colour"). No health refusal: sidecar **660 samples, 0 unhealthy, no refresh error**; console transcript
  captured (437 lines). Mac on AC with the owner's `caffeinate -i -s` (both assertions verified before and
  after) plus the launcher's `caffeinate -i -w`.

## Calibration (15 tasks per deployment; frozen rule: fixed-strong = highest success, fixed-fast = lowest p50)
| deployment | success | 95 % CI | completion | violations | p50 |
|---|---|---|---|---|---|
| qwen3.8:latest | **1.000** (15/15) | [0.796, 1.0] | 1.000 | 0 | 3218 ms |
| qwen3-coder:latest | 0.933 (14/15) | [0.702, 0.988] | 0.933 | 1 (`vis-01`) | **501 ms** |
| qwen3-coder-next:latest | 0.933 (14/15) | [0.702, 0.988] | 0.933 | 1 (`vis-01`) | 764 ms |
| gemma4:31b | 0.800 (12/15) | [0.548, 0.930] | 1.000 | 0 | 21274 ms |
| muse-glimmer:latest | 0.800 (12/15) | [0.548, 0.930] | 0.933 | 1 (`vis-01`) | 21804 ms |
| qwen3.6-fast:latest | 0.600 (9/15) | [0.357, 0.802] | 1.000 | 0 | 4201 ms |
| qwen3.6-accurate:latest | 0.533 (8/15) | [0.301, 0.752] | 1.000 | 0 | 5465 ms |
| qwen3.6:latest | 0.400 (6/15) | [0.198, 0.643] | 1.000 | 0 | 3980 ms |

fixed-strong → **qwen3.8:latest**; fixed-fast → **qwen3-coder:latest** (the same two as Pass 1b and Pass 2).

## Held-out results (32 tasks; Wilson 95 % intervals; reproduced from the records by `scripts/eval_aggregate.py`)
| policy | success | 95 % CI | completion | violations | p50 | p95 |
|---|---|---|---|---|---|---|
| **auto** (deterministic router) | **0.938** (30/32) | [0.799, 0.983] | 1.000 | 0 | 3001 ms | 10621 ms |
| fixed-strong (qwen3.8) | 0.938 (30/32) | [0.799, 0.983] | 1.000 | 0 | 2987 ms | 10702 ms |
| fixed-fast (qwen3-coder) | 0.938 (30/32) | [0.799, 0.983] | 0.969 | 1 | 479 ms | 4848 ms |
| rules (gold-category diagnostic, not deployable) | 0.844 (27/32) | [0.682, 0.931] | 1.000 | 0 | 1630 ms | 6050 ms |
| random (seeded diagnostic) | 0.812 (26/32) | [0.647, 0.911] | 1.000 | 0 | 4538 ms | 29530 ms |
| oracle (offline upper bound, not available at runtime) | 1.000 (32/32) | [0.893, 1.0] | 1.000 | 0 | 439 ms | 1960 ms |

Per-deployment test sweeps: qwen3.8 0.938, gemma4 0.938, qwen3-coder 0.938 (1 violation), qwen3-coder-next 0.938
(1 violation), **muse-glimmer 0.688** (1 violation; p50 22.3 s), qwen3.6 0.594, qwen3.6-fast 0.594,
qwen3.6-accurate 0.562. Time-to-first-token is not recorded by the frozen harness.

**auto vs fixed-strong: identical.** `auto` selected **qwen3.8 on all 32 tasks** — the fixed-strong model —
so the two policies share every outcome (both fail `code-05` and `cont-01`): paired difference **0.000**, no
discordant task (the paired interval collapses to [0, 0]); latency p50 +14 ms, p95 −81 ms. Against
fixed-fast, `auto` avoided the one capability violation (`vis-02`) at the cost of the thinking model's
latency (p50 3.0 s vs 0.48 s).

## Routing — why qwen3.8 everywhere (descriptive; no routing change follows)
On the 31 non-vision tasks the three top candidates all carried measured quality 1.00 for the inferred
task; the frozen `quality` profile then scored **qwen3.8 0.9607** (latency cost 0.148, residency 0.0,
load/overhead 0.343), **qwen3-coder 0.9428** (0.023, **0.359**, 0.359) and **qwen3-coder-next 0.8447**
(0.035, 1.0, 1.0). qwen3-coder's latency advantage (worth +0.019) was smaller than its residency penalty plus the
slightly larger load heuristic (−0.037 relative to qwen3.8): it was **not resident when the `auto` phase began**, whereas qwen3.8 was (the sweep
order ended with qwen3.6-fast; `/api/ps` after the run: qwen3.8 and qwen3.6-fast resident). In Pass 1b and
Pass 2 the opposite state held (qwen3-coder and qwen3.8 resident) and `auto` chose qwen3-coder 31/32.
**The router's choice among measured-equal candidates is therefore decided by residency state at decision
time — an artefact of which sweep ran last in the harness, not of the tasks.** On `vis-02` the three
non-vision models were excluded and qwen3.8 (0.9403) won over qwen3.6-fast (0.9204). gemma4 and
muse-glimmer never came close (latency cost ≈ 1.0); the qwen3.6 variants lost on measured quality
(0.0–0.72 on most tasks). Routing overhead: mean 0.38 ms, p50 0.30 ms, p95 0.50 ms, max 2.91 ms. Task-label
accuracy 0.844 (27/32; 6 flagged ambiguous). Every `auto` choice was resident at decision time.

## Reasoning budget (`reasoning-budget-analysis.json`)
No finish reason or token usage is recorded, so no event is **proven** budget-limited; primary scores are
unchanged and nothing was rerun at a higher budget. Of 90 failed records, **40 are SUSPECTED budget-limited**
(10 empty content, 19 code with no function defined, 11 no usable number/JSON) — on qwen3.6 (12),
qwen3.6-accurate (10), qwen3.6-fast (9), gemma4 (5), muse-glimmer (4); **0 in `auto`, 0 on fixed-strong**.
The optional sensitivity run was **not** performed (owner instruction).

## Acceptance against the predeclared targets (`acceptance.md`)
capability violations 0 **PASS** · completion 1.000 ≥ 1.000 **PASS** · success 0.938 ≥ 0.888 **PASS** ·
overhead p95 0.5 ms < 5 ms **PASS** · classifier target not applicable. Disposition unchanged (1 — deterministic
routing baseline accepted, decided on Pass 1b). Stage C adds no success advantage for `auto` over the strongest
single model (identical outcomes) and no claim of general superiority.

## Material limits (read before quoting)
1. **Cross-runtime vs Pass 1b** (0.40.3 → 0.40.5); Pass 2 did not isolate the added model and never selected it.
2. **Residency-state artefact** (above): `auto` ≡ fixed-strong here because qwen3.8 was resident; a different
   sweep order would likely have produced the Pass 1b/2 pattern. The runs do not measure routing under
   realistic residency churn.
3. **Capability probe vs declaration**: muse-glimmer's vision was probed unsupported; its vision-task refusals
   count as capability violations in its sweep, and it was excluded from vision tasks under `auto`.
4. **Budget events SUSPECTED**, not proven; the four thinking-family sweeps (qwen3.6 variants, gemma4,
   muse-glimmer) are dominated by the 400-token budget.
5. **Production service not observed**: `/healthz` unreachable from the Mac before and after (placement A
   never contacted it). 6. DERP-relayed Mac→GX10 path in every latency column equally.

## Evidence
Folder `docs/live-runs/2026-10-24-gx10-stage-c/` (`MANIFEST.md`). Canonical Mac run files: report
`stage-c.json` sha256 `f7cdd2e8d1d4edda613886351b5f9edc8f5cfbc3278f2286c7895d549ad45972`; checkpoint
`stage-c.records.jsonl` sha256 `1bf93d845d88d647d35e827282d7cfd5cea7e50b8ff1dc5028f6d8836cd67353` (public
copy byte-identical). The public report copy is path-redacted (`<EVAL_CHECKOUT>`, `<RUN_ROOT>`; sha256
`78efb3d0c2ed817a…` recorded in `environment.json`) and equals the canonical object once the placeholders are
restored. `scripts/eval_aggregate.py`: "all aggregates in the report match the records" (canonical and public).

## STOP — confirmed
No Ollama, GX10 service, model-tag, registry, evaluator, scorer, configuration or routing-policy change;
classifier OFF; Pass 1/1b/2 unchanged; no sensitivity run; no tag, no PyPI package, no container image.
